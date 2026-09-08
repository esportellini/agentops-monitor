"""Human approval workflow layered on top of deterministic policy decisions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Severity
from app.models.security import AgentPolicy, ToolApproval
from app.models.trace import Span, Trace
from app.services import audit as audit_svc
from app.services.ingest_security import persist_findings
from app.services.policy import (
    PolicyDecision,
    ToolPolicyResult,
    apply_security_actions,
    evaluate_tool_preflight,
    resolve_agent_policy,
    sanitize_target_url,
)
from app.services.security import scan_and_redact_object


@dataclass(frozen=True)
class ApprovalPolicyResult:
    policy: ToolPolicyResult
    approval_id: int | None = None
    external_request_id: str | None = None
    approval_status: str | None = None


def _with_decision(base: ToolPolicyResult, decision: PolicyDecision, code: str, reason: str) -> ToolPolicyResult:
    return ToolPolicyResult(decision, code, reason, base.policy_id, base.limits)


async def _safe_context(
    db: AsyncSession,
    trace: Trace,
    policy: AgentPolicy | None,
    context: dict | None,
) -> dict | None:
    if context is None:
        return None
    scan = scan_and_redact_object(context, "approval_context")
    secured = apply_security_actions(scan, policy, "approval_context")
    if scan.matches:
        await persist_findings(db, trace=trace, matches=scan.matches, policy=policy)
    return secured.sanitized


async def _safe_target(
    db: AsyncSession,
    trace: Trace,
    policy: AgentPolicy | None,
    target_url: str | None,
) -> str | None:
    safe_url = sanitize_target_url(target_url)
    if safe_url is None:
        return None
    scan = scan_and_redact_object(safe_url, "approval_target_url")
    secured = apply_security_actions(scan, policy, "approval_target_url")
    if scan.matches:
        await persist_findings(db, trace=trace, matches=scan.matches, policy=policy)
    return secured.sanitized


def _matches_attempt(
    approval: ToolApproval,
    trace: Trace,
    tool_name: str,
    target_url: str | None,
    context: dict | None,
) -> bool:
    return (
        approval.trace_id == trace.id
        and approval.agent_id == trace.agent_id
        and approval.tool_name.strip().lower() == tool_name.strip().lower()
        and approval.target_url == target_url
        and approval.tool_input == context
    )


async def check_tool_with_approval(
    db: AsyncSession,
    *,
    trace: Trace,
    tool_name: str,
    target_url: str | None,
    external_request_id: str | None,
    external_span_id: str | None,
    approval_context: dict | None,
) -> ApprovalPolicyResult:
    base = await evaluate_tool_preflight(db, trace, tool_name, target_url)
    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)
    request_id = external_request_id or str(uuid4())
    existing = await db.scalar(select(ToolApproval).where(
        ToolApproval.organization_id == trace.organization_id,
        ToolApproval.external_request_id == request_id,
    ))
    if existing is None and base.decision != PolicyDecision.REQUIRE_APPROVAL:
        return ApprovalPolicyResult(base)

    safe_url = await _safe_target(db, trace, policy, target_url)
    safe_context = await _safe_context(db, trace, policy, approval_context)
    if existing is not None:
        if not _matches_attempt(existing, trace, tool_name, safe_url, safe_context):
            blocked = _with_decision(
                base, PolicyDecision.BLOCK, "APPROVAL_CONTEXT_MISMATCH",
                "Approval request does not match this tool attempt",
            )
            return ApprovalPolicyResult(blocked, existing.id, request_id, existing.status)
        if base.decision == PolicyDecision.BLOCK:
            return ApprovalPolicyResult(base, existing.id, request_id, existing.status)
        if existing.status == "rejected":
            blocked = _with_decision(
                base, PolicyDecision.BLOCK, "APPROVAL_REJECTED", "Approval was rejected"
            )
            return ApprovalPolicyResult(blocked, existing.id, request_id, "rejected")
        if existing.used_at is not None:
            blocked = _with_decision(
                base, PolicyDecision.BLOCK, "APPROVAL_ALREADY_USED",
                "Approval was already used for an execution",
            )
            return ApprovalPolicyResult(blocked, existing.id, request_id, "used")
        if existing.status == "approved":
            allowed = _with_decision(
                base, PolicyDecision.ALLOW, "APPROVAL_GRANTED", "Approval is valid"
            )
            return ApprovalPolicyResult(allowed, existing.id, request_id, "approved")
        if base.decision == PolicyDecision.ALLOW:
            return ApprovalPolicyResult(base, existing.id, request_id, existing.status)
        return ApprovalPolicyResult(base, existing.id, request_id, "pending")

    span_id = None
    if external_span_id:
        span_id = await db.scalar(select(Span.id).where(
            Span.trace_id == trace.id, Span.external_span_id == external_span_id,
        ))
    approval = ToolApproval(
        organization_id=trace.organization_id,
        trace_id=trace.id,
        span_id=span_id,
        agent_id=trace.agent_id,
        external_request_id=request_id,
        tool_name=tool_name.strip().lower(),
        tool_input=safe_context,
        target_url=safe_url,
        status="pending",
    )
    db.add(approval)
    await db.flush()
    await audit_svc.write(
        db,
        organization_id=trace.organization_id,
        event_type="tool_approval.created",
        entity_type="tool_approval",
        entity_id=str(approval.id),
        message="Tool approval request created",
        after_data={
            "approval_id": approval.id, "tool": approval.tool_name,
            "trace_id": trace.id, "agent_id": trace.agent_id, "status": "pending",
        },
    )
    return ApprovalPolicyResult(base, approval.id, request_id, "pending")


async def transition_approval(
    db: AsyncSession,
    *,
    approval_id: int,
    organization_id: int,
    reviewer_id: int,
    outcome: str,
    note: str | None,
) -> ToolApproval | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(ToolApproval)
        .where(
            ToolApproval.id == approval_id,
            ToolApproval.organization_id == organization_id,
            ToolApproval.status == "pending",
        )
        .values(
            status=outcome,
            reviewed_by_id=reviewer_id,
            reviewed_at=now,
            review_note=note,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        return None
    approval = await db.scalar(select(ToolApproval).where(ToolApproval.id == approval_id))
    await audit_svc.write(
        db,
        organization_id=organization_id,
        user_id=reviewer_id,
        event_type=f"tool_approval.{outcome}",
        entity_type="tool_approval",
        entity_id=str(approval_id),
        severity=Severity.INFO,
        message=f"Tool approval request {outcome}",
        after_data={
            "approval_id": approval_id, "tool": approval.tool_name,
            "trace_id": approval.trace_id, "agent_id": approval.agent_id,
            "reviewer_id": reviewer_id, "status": outcome,
        },
    )
    return approval
