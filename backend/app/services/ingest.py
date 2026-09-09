"""
Ingest service: all writes that come through the SDK-facing API.

Design decisions:
- Idempotency: trace_start with a known external_trace_id returns the existing
  trace instead of creating a duplicate. Same for spans.
- Aggregation (token sums, cost sums) happens in-transaction on trace_finish,
  keeping it simple and consistent without a background worker.
- last_used_at is updated by the auth layer, committed here.
- No chain-of-thought or private reasoning is stored — only the fields the
  SDK explicitly sends.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ingest_auth import IngestContext
from app.core.logging import get_logger
from app.models.enums import (
    ModelCallStatus,
    Severity,
    SpanStatus,
    TraceStatus,
    ToolCallStatus,
)
from app.models.trace import (
    CostRecord,
    ModelCall,
    Span,
    ToolCall,
    Trace,
    TraceEvent,
)
from app.models.project import Agent, Environment, Project
from app.models.security import AgentPolicy, ToolApproval
from app.repositories import trace as trace_repo
from app.schemas.ingest import (
    ModelCallCreate,
    SpanCreate,
    SpanUpdate,
    ToolCallCreate,
    TraceEventCreate,
    TraceFinish,
    TraceStart,
)
from app.services.ingest_security import max_severity, persist_findings, persist_policy_finding
from app.services.policy import (
    LimitState,
    PolicyDecision,
    apply_security_actions,
    evaluate_domain,
    evaluate_tool,
    evaluate_tool_preflight,
    evaluate_trace_limits,
    resolve_agent_policy,
)
from app.services import audit as audit_svc
from app.services.alerts import TRACE_FINISHED, RuntimeAlertEvent, evaluate_runtime_event
from app.services.pricing import PRICED, UNPRICED, resolve_model_call_pricing
from app.services.security import (
    FINDING_COST_LIMIT,
    FINDING_DOMAIN_BLOCKED,
    FINDING_TOKEN_LIMIT,
    FINDING_TOOL_UNAUTHORIZED,
    RuleMatch,
    StructuredScanResult,
    scan_and_redact_object,
)

log = get_logger(__name__)


class IngestError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(start: datetime, end: datetime) -> int:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    delta = end - start
    return max(0, int(delta.total_seconds() * 1000))


def _scan(value: object, field_path: str) -> StructuredScanResult:
    result = scan_and_redact_object(value, field_path)
    log.info(
        "security.scan.completed",
        field_path=field_path,
        finding_count=len(result.matches),
        redaction_count=sum(1 for match in result.matches if match.redaction_placeholder),
    )
    if any(match.redaction_placeholder for match in result.matches):
        log.info(
            "security.payload.redacted",
            field_path=field_path,
            redaction_count=sum(1 for match in result.matches if match.redaction_placeholder),
        )
    return result


def _secure_scan(value: object, field_path: str, policy: AgentPolicy | None) -> StructuredScanResult:
    return apply_security_actions(_scan(value, field_path), policy, field_path)


async def _trace_for_span(db: AsyncSession, span: Span) -> Trace:
    trace = await db.scalar(select(Trace).where(Trace.id == span.trace_id))
    if trace is None:
        raise IngestError("Trace for span not found", status_code=404)
    return trace


async def _persist_scans(
    db: AsyncSession,
    trace: Trace,
    scans: list[StructuredScanResult],
    *,
    span: Span | None = None,
    policy: AgentPolicy | None = None,
) -> None:
    matches: list[RuleMatch] = [match for scan in scans for match in scan.matches]
    if matches:
        await persist_findings(db, trace=trace, span=span, matches=matches, policy=policy)


async def _validate_project_scope(
    db: AsyncSession, ctx: IngestContext, project_id: int | None
) -> int:
    """
    Return the resolved project_id, enforcing key scope.
    - If the key is project-scoped: project_id must match (or be omitted).
    - If the key is org-scoped: project_id is used as-is (or raises if None).
    """
    if ctx.project_id is not None and project_id is not None and project_id != ctx.project_id:
        log.warning("ingest.scope_rejected", resource_type="project")
        raise IngestError("API key is not authorized for this project", status_code=403)

    resolved_project_id = ctx.project_id or project_id
    if resolved_project_id is None:
        raise IngestError("project_id is required for org-scoped keys", status_code=400)

    owned_project_id = await db.scalar(
        select(Project.id).where(
            Project.id == resolved_project_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if owned_project_id is None:
        log.warning("ingest.scope_rejected", resource_type="project")
        raise IngestError("API key is not authorized for this project", status_code=403)
    return resolved_project_id


async def _validate_trace_references(
    db: AsyncSession,
    *,
    project_id: int,
    agent_id: int | None,
    environment_id: int | None,
) -> None:
    checks = (
        ("agent", Agent, agent_id),
        ("environment", Environment, environment_id),
    )
    for resource_type, model, resource_id in checks:
        if resource_id is None:
            continue
        allowed_id = await db.scalar(
            select(model.id).where(model.id == resource_id, model.project_id == project_id)
        )
        if allowed_id is None:
            log.warning(
                "ingest.scope_rejected",
                resource_type=resource_type,
                project_id=project_id,
            )
            raise IngestError(
                "API key is not authorized for this resource", status_code=403
            )


# ── Trace ──────────────────────────────────────────────────────────────────────

async def start_trace(
    db: AsyncSession,
    ctx: IngestContext,
    body: TraceStart,
) -> Trace:
    # Idempotency: return existing trace if same external_trace_id in this org
    existing = await trace_repo.get_trace_by_external_id(
        db, body.external_trace_id, ctx.organization_id
    )
    if existing:
        log.info("ingest.trace.idempotent", external_trace_id=body.external_trace_id)
        return existing

    project_id = await _validate_project_scope(db, ctx, body.project_id)
    await _validate_trace_references(
        db,
        project_id=project_id,
        agent_id=body.agent_id,
        environment_id=body.environment_id,
    )

    policy = await resolve_agent_policy(db, ctx.organization_id, body.agent_id)
    metadata_scan = _secure_scan(body.metadata, "metadata", policy)
    trace = Trace(
        organization_id=ctx.organization_id,
        project_id=project_id,
        agent_id=body.agent_id,
        environment_id=body.environment_id,
        external_trace_id=body.external_trace_id,
        session_id=body.session_id,
        user_reference=body.user_reference,
        name=body.name,
        status=TraceStatus.RUNNING,
        started_at=body.started_at,
        metadata_=metadata_scan.sanitized,
    )
    db.add(trace)
    await db.flush()
    await _persist_scans(db, trace, [metadata_scan], policy=policy)
    log.info("ingest.trace.started", trace_id=trace.id, external=body.external_trace_id)
    return trace


async def finish_trace(
    db: AsyncSession,
    ctx: IngestContext,
    external_trace_id: str,
    body: TraceFinish,
) -> Trace:
    trace = await trace_repo.get_trace_by_external_id(db, external_trace_id, ctx.organization_id)
    if trace is None:
        raise IngestError(f"Trace '{external_trace_id}' not found", status_code=404)

    if trace.status != TraceStatus.RUNNING:
        await _evaluate_trace_alerts(db, trace)
        return trace

    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)
    metadata_scan = _secure_scan(body.metadata, "metadata", policy)
    trace.status = body.status
    trace.ended_at = body.ended_at
    trace.duration_ms = _duration_ms(trace.started_at, body.ended_at)
    trace.risk_level = max_severity(trace.risk_level, body.risk_level)
    if body.metadata:
        trace.metadata_ = {**(trace.metadata_ or {}), **metadata_scan.sanitized}

    await _persist_scans(db, trace, [metadata_scan], policy=policy)

    # Aggregate token and cost totals from all model calls in this trace
    agg = await db.execute(
        select(
            func.coalesce(func.sum(ModelCall.input_tokens), 0),
            func.coalesce(func.sum(ModelCall.output_tokens), 0),
            func.coalesce(
                func.sum(
                    case(
                        (ModelCall.pricing_status == PRICED, ModelCall.estimated_cost),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((ModelCall.pricing_status == UNPRICED, 1), else_=0)),
                0,
            ),
        )
        .join(Span, Span.id == ModelCall.span_id)
        .where(Span.trace_id == trace.id)
    )
    row = agg.one()
    trace.total_input_tokens = int(row[0])
    trace.total_output_tokens = int(row[1])
    trace.total_cost = row[2]
    trace.unpriced_model_calls = int(row[3])

    log.info(
        "ingest.trace.finished",
        trace_id=trace.id,
        status=body.status,
        duration_ms=trace.duration_ms,
        tokens_in=trace.total_input_tokens,
        tokens_out=trace.total_output_tokens,
        cost=trace.total_cost,
    )
    await _evaluate_trace_alerts(db, trace)
    return trace


async def _evaluate_trace_alerts(db: AsyncSession, trace: Trace) -> None:
    await evaluate_runtime_event(db, RuntimeAlertEvent(
        event_type=TRACE_FINISHED,
        organization_id=trace.organization_id,
        project_id=trace.project_id,
        agent_id=trace.agent_id,
        trace_id=trace.id,
        span_id=None,
        source_type="trace",
        source_id=str(trace.id),
        occurred_at=trace.ended_at or datetime.now(timezone.utc),
        data={
            "trace_status": trace.status.value,
            "risk_level": trace.risk_level.value,
            "total_cost_usd": trace.total_cost,
            "total_tokens": trace.total_input_tokens + trace.total_output_tokens,
            "duration_ms": trace.duration_ms,
            "unpriced_model_calls": trace.unpriced_model_calls,
        },
    ))


# ── Span ───────────────────────────────────────────────────────────────────────

async def create_span(
    db: AsyncSession,
    ctx: IngestContext,
    external_trace_id: str,
    body: SpanCreate,
) -> Span:
    trace = await trace_repo.get_trace_by_external_id(db, external_trace_id, ctx.organization_id)
    if trace is None:
        raise IngestError(f"Trace '{external_trace_id}' not found", status_code=404)

    # Idempotency: same external_span_id in same trace → return existing
    existing = await trace_repo.get_span_by_external_id(db, body.external_span_id, trace.id)
    if existing:
        log.info("ingest.span.idempotent", external_span_id=body.external_span_id)
        return existing

    # Resolve parent span
    parent_db_id: int | None = None
    if body.parent_span_id:
        parent = await trace_repo.get_span_by_external_id(db, body.parent_span_id, trace.id)
        if parent:
            parent_db_id = parent.id
        else:
            log.warning(
                "ingest.span.parent_not_found",
                parent_external_id=body.parent_span_id,
                trace_id=trace.id,
            )

    duration: int | None = None
    if body.ended_at:
        duration = _duration_ms(body.started_at, body.ended_at)

    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)
    input_scan = _secure_scan(body.input_data, "input_data", policy)
    output_scan = _secure_scan(body.output_data, "output_data", policy)
    error_scan = _secure_scan(body.error_data, "error_data", policy)
    metadata_scan = _secure_scan(body.metadata, "metadata", policy)
    span = Span(
        trace_id=trace.id,
        parent_span_id=parent_db_id,
        external_span_id=body.external_span_id,
        name=body.name,
        type=body.type,
        status=body.status,
        started_at=body.started_at,
        ended_at=body.ended_at,
        duration_ms=duration,
        input_data=input_scan.sanitized if policy is None or policy.capture_inputs else None,
        output_data=output_scan.sanitized if policy is None or policy.capture_outputs else None,
        error_data=error_scan.sanitized,
        metadata_=metadata_scan.sanitized,
    )
    db.add(span)
    await db.flush()
    await _persist_scans(
        db, trace, [input_scan, output_scan, error_scan, metadata_scan], span=span, policy=policy
    )
    return span


async def update_span(
    db: AsyncSession,
    ctx: IngestContext,
    external_span_id: str,
    body: SpanUpdate,
) -> Span:
    span = await trace_repo.get_span_by_external_id_in_org(db, external_span_id, ctx.organization_id)
    if span is None:
        raise IngestError(f"Span '{external_span_id}' not found", status_code=404)

    trace = await _trace_for_span(db, span)
    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)
    scans: list[StructuredScanResult] = []

    if body.status is not None:
        span.status = body.status
    if body.ended_at is not None:
        span.ended_at = body.ended_at
        span.duration_ms = _duration_ms(span.started_at, body.ended_at)
    if body.output_data is not None:
        output_scan = _secure_scan(body.output_data, "output_data", policy)
        span.output_data = output_scan.sanitized if policy is None or policy.capture_outputs else None
        scans.append(output_scan)
    if body.error_data is not None:
        error_scan = _secure_scan(body.error_data, "error_data", policy)
        span.error_data = error_scan.sanitized
        scans.append(error_scan)
    if body.metadata is not None:
        metadata_scan = _secure_scan(body.metadata, "metadata", policy)
        span.metadata_ = {**(span.metadata_ or {}), **metadata_scan.sanitized}
        scans.append(metadata_scan)

    await _persist_scans(db, trace, scans, span=span, policy=policy)

    return span


# ── ToolCall ───────────────────────────────────────────────────────────────────

async def create_tool_call(
    db: AsyncSession,
    ctx: IngestContext,
    external_span_id: str,
    body: ToolCallCreate,
) -> ToolCall:
    span = await trace_repo.get_span_by_external_id_in_org(db, external_span_id, ctx.organization_id)
    if span is None:
        raise IngestError(f"Span '{external_span_id}' not found", status_code=404)

    trace = await _trace_for_span(db, span)
    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)

    approval: ToolApproval | None = None
    if body.approval_id is not None:
        if body.status not in {ToolCallStatus.SUCCESS, ToolCallStatus.ERROR}:
            raise IngestError("Approval provenance requires an executed tool status")
        existing_call = await db.scalar(
            select(ToolCall)
            .join(Span, Span.id == ToolCall.span_id)
            .join(Trace, Trace.id == Span.trace_id)
            .where(
                ToolCall.approval_id == body.approval_id,
                Trace.organization_id == trace.organization_id,
            )
        )
        if existing_call is not None:
            if existing_call.span_id == span.id and existing_call.tool_name.strip().lower() == body.tool_name.strip().lower():
                return existing_call
            raise IngestError("Approval is not valid for this tool call", status_code=403)

        approval = await db.scalar(select(ToolApproval).where(
            ToolApproval.id == body.approval_id,
            ToolApproval.organization_id == trace.organization_id,
            ToolApproval.trace_id == trace.id,
            ToolApproval.agent_id == trace.agent_id,
        ))
        if approval is None or approval.tool_name.strip().lower() != body.tool_name.strip().lower():
            raise IngestError("Approval is not valid for this tool call", status_code=403)
        if approval.span_id is not None and approval.span_id != span.id:
            raise IngestError("Approval is not valid for this tool call", status_code=403)
        if approval.status != "approved" or approval.used_at is not None:
            raise IngestError("Approval is not available for execution", status_code=409)
        current = await evaluate_tool_preflight(db, trace, body.tool_name, approval.target_url)
        if current.decision == PolicyDecision.BLOCK:
            raise IngestError(current.reason_code, status_code=403)
        consumed_at = _utcnow()
        consumed = await db.execute(
            update(ToolApproval)
            .where(
                ToolApproval.id == approval.id,
                ToolApproval.status == "approved",
                ToolApproval.used_at.is_(None),
            )
            .values(used_at=consumed_at, updated_at=consumed_at)
        )
        if consumed.rowcount != 1:
            raise IngestError("Approval is not available for execution", status_code=409)
        approval.used_at = consumed_at

    input_scan = _secure_scan(body.input_data, "tool_call.input_data", policy)
    output_scan = _secure_scan(body.output_data, "tool_call.output_data", policy)

    tc = ToolCall(
        span_id=span.id,
        tool_name=body.tool_name,
        input_data=input_scan.sanitized if policy is None or policy.capture_inputs else None,
        output_data=output_scan.sanitized if policy is None or policy.capture_outputs else None,
        status=body.status,
        duration_ms=body.duration_ms,
        requires_approval=body.requires_approval,
        blocked_reason=body.blocked_reason,
        approval_id=approval.id if approval else None,
        approved_by_id=approval.reviewed_by_id if approval else None,
    )
    db.add(tc)
    await db.flush()
    await _persist_scans(db, trace, [input_scan, output_scan], span=span, policy=policy)

    if approval is not None:
        await audit_svc.write(
            db,
            organization_id=trace.organization_id,
            event_type="tool_approval.executed",
            entity_type="tool_approval",
            entity_id=str(approval.id),
            message="Approved tool execution recorded",
            after_data={
                "approval_id": approval.id, "tool": tc.tool_name,
                "trace_id": trace.id, "agent_id": trace.agent_id,
                "tool_call_id": tc.id, "outcome": body.status.value,
            },
        )

    decision, reason_code, reason = evaluate_tool(policy, body.tool_name)
    executed = body.status in {ToolCallStatus.SUCCESS, ToolCallStatus.ERROR}
    if executed and decision != PolicyDecision.ALLOW:
        await persist_policy_finding(
            db, trace=trace, span=span, finding_type=FINDING_TOOL_UNAUTHORIZED,
            severity=Severity.HIGH, title="Unauthorized tool use", description=reason,
            reason_code=reason_code, evidence={
                "tool_name": body.tool_name.strip().lower(), "policy_id": policy.id,
            },
        )
    target_url = None
    if isinstance(body.input_data, dict):
        candidate = body.input_data.get("target_url", body.input_data.get("url"))
        target_url = candidate if isinstance(candidate, str) else None
    domain_allowed, domain_code, domain_reason = evaluate_domain(policy, target_url)
    if executed and not domain_allowed:
        await persist_policy_finding(
            db, trace=trace, span=span, finding_type=FINDING_DOMAIN_BLOCKED,
            severity=Severity.HIGH, title="Blocked target domain", description=domain_reason,
            reason_code=domain_code, evidence={"policy_id": policy.id},
        )
    return tc


# ── ModelCall ──────────────────────────────────────────────────────────────────

async def create_model_call(
    db: AsyncSession,
    ctx: IngestContext,
    external_span_id: str,
    body: ModelCallCreate,
) -> ModelCall:
    span = await trace_repo.get_span_by_external_id_in_org(db, external_span_id, ctx.organization_id)
    if span is None:
        raise IngestError(f"Span '{external_span_id}' not found", status_code=404)

    trace = await _trace_for_span(db, span)
    resolution = await resolve_model_call_pricing(
        db,
        organization_id=trace.organization_id,
        provider=body.provider,
        model=body.model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        at=body.occurred_at,
    )
    persisted_cost = resolution.cost_usd or Decimal("0.00000000")
    pricing = resolution.pricing

    mc = ModelCall(
        span_id=span.id,
        provider=resolution.provider,
        model=resolution.model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        estimated_cost=persisted_cost,
        occurred_at=resolution.occurred_at,
        pricing_status=resolution.status,
        pricing_id=pricing.id if pricing else None,
        latency_ms=body.latency_ms,
        temperature=body.temperature,
        status=body.status,
    )
    db.add(mc)
    await db.flush()

    # Every call gets an immutable accounting snapshot. UNPRICED is stored
    # explicitly and therefore remains distinct from a configured zero price.
    db.add(CostRecord(
        organization_id=trace.organization_id,
        trace_id=trace.id,
        model_call_id=mc.id,
        provider=resolution.provider,
        model=resolution.model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        cost_usd=persisted_cost,
        pricing_status=resolution.status,
        pricing_id=pricing.id if pricing else None,
        input_price_per_million=pricing.input_price_per_million if pricing else None,
        output_price_per_million=pricing.output_price_per_million if pricing else None,
        pricing_effective_from=pricing.effective_from if pricing else None,
        recorded_at=resolution.occurred_at,
    ))

    await db.flush()
    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)
    limits = await evaluate_trace_limits(db, trace, policy)
    if limits.token_state == LimitState.EXCEEDED:
        await persist_policy_finding(
            db, trace=trace, finding_type=FINDING_TOKEN_LIMIT,
            severity=Severity.MEDIUM, title="Trace token limit exceeded",
            description="Persisted model usage exceeds the configured trace token limit",
            reason_code="TOKEN_LIMIT_EXCEEDED",
            evidence={
                "actual": limits.total_tokens, "limit": policy.max_tokens_per_trace,
                "policy_id": policy.id,
            },
        )
    if limits.cost_state == LimitState.EXCEEDED:
        await persist_policy_finding(
            db, trace=trace, finding_type=FINDING_COST_LIMIT,
            severity=Severity.MEDIUM, title="Trace cost limit exceeded",
            description="Authoritative priced usage exceeds the configured trace cost limit",
            reason_code="COST_LIMIT_EXCEEDED",
            evidence={
                "known_cost": str(limits.known_cost_usd),
                "limit": str(policy.max_cost_per_trace_usd),
                "unpriced_model_calls": limits.unpriced_model_calls,
                "policy_id": policy.id,
            },
        )

    return mc


# ── TraceEvent ─────────────────────────────────────────────────────────────────

async def create_event(
    db: AsyncSession,
    ctx: IngestContext,
    external_trace_id: str,
    body: TraceEventCreate,
) -> TraceEvent:
    trace = await trace_repo.get_trace_by_external_id(db, external_trace_id, ctx.organization_id)
    if trace is None:
        raise IngestError(f"Trace '{external_trace_id}' not found", status_code=404)

    span_db_id: int | None = None
    if body.span_id:
        span = await trace_repo.get_span_by_external_id(db, body.span_id, trace.id)
        if span:
            span_db_id = span.id

    policy = await resolve_agent_policy(db, trace.organization_id, trace.agent_id)
    message_scan = _secure_scan(body.message, "event.message", policy)
    metadata_scan = _secure_scan(body.metadata, "event.metadata", policy)

    event = TraceEvent(
        trace_id=trace.id,
        span_id=span_db_id,
        event_type=body.event_type,
        severity=body.severity,
        message=message_scan.sanitized,
        metadata_=metadata_scan.sanitized,
        created_at=body.created_at or _utcnow(),
    )
    db.add(event)
    await db.flush()
    await _persist_scans(
        db, trace, [message_scan, metadata_scan], span=span if body.span_id else None,
        policy=policy,
    )
    return event
