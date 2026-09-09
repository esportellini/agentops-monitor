"""
Security, policies, tool approvals and alerts API.
All endpoints are org-scoped.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator

from app.core.deps import OrgContext, require_analyst, require_org_member, require_role
from app.db.session import get_db
from app.models.alert import AlertIncident, AlertRule
from app.models.enums import AlertIncidentStatus, AlertRuleStatus, MemberRole, Severity
from app.models.security import AgentPolicy, SecurityFinding, ToolApproval
from app.models.project import Agent, Project
from app.models.trace import Trace
from app.services.approvals import transition_approval
from app.services.policy import normalize_policy_list
from app.services import alerts as alerts_svc
from app.services.security import scan_text, ALL_FINDING_TYPES, get_severity

router = APIRouter(prefix="/organizations/{org_id}", tags=["security"])


# ── Security findings ─────────────────────────────────────────────────────────

@router.get("/security/findings")
async def list_findings(
    finding_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    resolved: bool | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    q = select(SecurityFinding).where(SecurityFinding.organization_id == ctx.org_id)
    if finding_type:
        q = q.where(SecurityFinding.finding_type == finding_type)
    if severity:
        q = q.where(SecurityFinding.severity == Severity(severity))
    if agent_id:
        q = q.where(SecurityFinding.agent_id == agent_id)
    if resolved is True:
        q = q.where(SecurityFinding.resolved_at.isnot(None))
    elif resolved is False:
        q = q.where(SecurityFinding.resolved_at.is_(None))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(SecurityFinding.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    return {"total": total, "items": [_finding_out(f) for f in rows]}


@router.get("/security/findings/{finding_id}")
async def get_finding(
    finding_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SecurityFinding).where(
            SecurityFinding.id == finding_id,
            SecurityFinding.organization_id == ctx.org_id,
        )
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    return _finding_out(f)


@router.patch("/security/findings/{finding_id}/resolve")
async def resolve_finding(
    finding_id: int,
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SecurityFinding).where(
            SecurityFinding.id == finding_id,
            SecurityFinding.organization_id == ctx.org_id,
        )
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    f.resolved_at = datetime.now(timezone.utc)
    f.resolved_by_id = ctx.user_id
    f.resolution_note = payload.get("note")
    await db.commit()
    return _finding_out(f)


# ── Security overview ─────────────────────────────────────────────────────────

@router.get("/security/overview")
async def security_overview(
    days: int = Query(default=30, ge=1, le=365),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Counts by severity
    sev_rows = (await db.execute(
        select(SecurityFinding.severity, func.count())
        .where(SecurityFinding.organization_id == ctx.org_id, SecurityFinding.created_at >= since)
        .group_by(SecurityFinding.severity)
    )).all()

    # Counts by finding type
    type_rows = (await db.execute(
        select(SecurityFinding.finding_type, func.count())
        .where(SecurityFinding.organization_id == ctx.org_id, SecurityFinding.created_at >= since)
        .group_by(SecurityFinding.finding_type)
        .order_by(func.count().desc())
        .limit(10)
    )).all()

    # Top agents by finding count
    agent_rows = (await db.execute(
        select(SecurityFinding.agent_id, func.count())
        .where(
            SecurityFinding.organization_id == ctx.org_id,
            SecurityFinding.created_at >= since,
            SecurityFinding.agent_id.isnot(None),
        )
        .group_by(SecurityFinding.agent_id)
        .order_by(func.count().desc())
        .limit(5)
    )).all()

    # Unresolved count
    unresolved = (await db.execute(
        select(func.count()).where(
            SecurityFinding.organization_id == ctx.org_id,
            SecurityFinding.resolved_at.is_(None),
        )
    )).scalar_one()

    return {
        "unresolved_total": unresolved,
        "by_severity": {
            sev.value if isinstance(sev, Severity) else str(sev): cnt
            for sev, cnt in sev_rows
        },
        "by_type": [{"finding_type": t, "count": c} for t, c in type_rows],
        "top_agents": [{"agent_id": aid, "count": c} for aid, c in agent_rows],
    }


# ── Scan endpoint (on-demand) ─────────────────────────────────────────────────

@router.post("/security/scan")
async def scan_content(
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    """
    On-demand scan of arbitrary text content.
    Returns findings without persisting them — useful for testing policies.
    """
    text = payload.get("text", "")
    if not isinstance(text, str):
        text = str(text)

    result = scan_text(text, field_name=payload.get("field_name", ""))
    return {
        "has_findings": result.has_findings,
        "highest_severity": result.highest_severity,
        "text_redacted": result.text_redacted if result.has_findings else None,
        "findings": [
            {
                "finding_type": m.finding_type,
                "severity": m.severity,
                "title": m.title,
                "description": m.description,
                "matched_text": (
                    m.redaction_placeholder
                    if m.redaction_placeholder
                    else (m.matched_text[:50] if m.matched_text else None)
                ),
                "has_redaction": m.redaction_placeholder is not None,
            }
            for m in result.matches
        ],
    }


# ── Agent policies ────────────────────────────────────────────────────────────

PolicyAction = Literal["detect", "redact", "alert", "block"]


class PolicyCreate(BaseModel):
    agent_id: int
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    tools_requiring_approval: list[str] | None = None
    max_tokens_per_trace: int | None = Field(default=None, ge=0)
    max_cost_per_trace_usd: float | None = Field(default=None, ge=0)
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    capture_inputs: bool = True
    capture_outputs: bool = True
    pii_action: PolicyAction = "alert"
    secret_action: PolicyAction = "block"
    injection_action: PolicyAction = "alert"
    active: bool = True

    @field_validator(
        "allowed_tools", "blocked_tools", "tools_requiring_approval",
        "allowed_domains", "blocked_domains",
    )
    @classmethod
    def normalize_lists(cls, value: list[str] | None) -> list[str] | None:
        return normalize_policy_list(value)


class PolicyUpdate(BaseModel):
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    tools_requiring_approval: list[str] | None = None
    max_tokens_per_trace: int | None = Field(default=None, ge=0)
    max_cost_per_trace_usd: float | None = Field(default=None, ge=0)
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    capture_inputs: bool = True
    capture_outputs: bool = True
    pii_action: PolicyAction = "alert"
    secret_action: PolicyAction = "block"
    injection_action: PolicyAction = "alert"
    active: bool = True

    @field_validator(
        "allowed_tools", "blocked_tools", "tools_requiring_approval",
        "allowed_domains", "blocked_domains",
    )
    @classmethod
    def normalize_lists(cls, value: list[str] | None) -> list[str] | None:
        return normalize_policy_list(value)

@router.get("/security/policies")
async def list_policies(
    agent_id: int | None = Query(default=None),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    q = select(AgentPolicy).where(AgentPolicy.organization_id == ctx.org_id)
    if agent_id:
        q = q.where(AgentPolicy.agent_id == agent_id)
    rows = (await db.execute(q.order_by(AgentPolicy.created_at.desc()))).scalars().all()
    return {"items": [_policy_out(p) for p in rows]}


@router.post("/security/policies", status_code=201)
async def create_policy(
    payload: PolicyCreate,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    owned_agent = await db.scalar(select(Agent.id).join(Project).where(
        Agent.id == payload.agent_id, Project.organization_id == ctx.org_id
    ))
    if owned_agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    existing = (await db.execute(
        select(AgentPolicy).where(
            AgentPolicy.agent_id == payload.agent_id,
            AgentPolicy.organization_id == ctx.org_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Policy already exists for this agent. Use PATCH.")

    p = AgentPolicy(organization_id=ctx.org_id, created_by_id=ctx.user_id, **payload.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _policy_out(p)


@router.patch("/security/policies/{policy_id}")
async def update_policy(
    policy_id: int,
    payload: PolicyUpdate,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    p = (await db.execute(
        select(AgentPolicy).where(
            AgentPolicy.id == policy_id,
            AgentPolicy.organization_id == ctx.org_id,
        )
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Policy not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(p, field, value)

    await db.commit()
    await db.refresh(p)
    return _policy_out(p)


# ── Tool approvals ────────────────────────────────────────────────────────────

class ApprovalReview(BaseModel):
    note: str | None = Field(default=None, max_length=2000)

@router.get("/tool-approvals")
async def list_approvals(
    status: str | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    tool: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, le=200),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    q = select(ToolApproval).where(ToolApproval.organization_id == ctx.org_id)
    if status:
        if status not in {"pending", "approved", "rejected", "used"}:
            raise HTTPException(status_code=422, detail="Invalid approval status")
        if status == "used":
            q = q.where(ToolApproval.used_at.isnot(None))
        else:
            q = q.where(ToolApproval.status == status, ToolApproval.used_at.is_(None))
    if agent_id is not None:
        q = q.where(ToolApproval.agent_id == agent_id)
    if tool:
        q = q.where(ToolApproval.tool_name == tool.strip().lower())
    rows = (await db.execute(q.order_by(ToolApproval.created_at.desc()).limit(limit))).scalars().all()
    return {"items": [await _approval_out(db, a) for a in rows]}


@router.get("/tool-approvals/{approval_id}")
async def get_approval(
    approval_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    approval = await db.scalar(select(ToolApproval).where(
        ToolApproval.id == approval_id,
        ToolApproval.organization_id == ctx.org_id,
    ))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return await _approval_out(db, approval)


@router.post("/tool-approvals/{approval_id}/approve")
async def approve_tool(
    approval_id: int,
    payload: ApprovalReview,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    a = await transition_approval(
        db, approval_id=approval_id, organization_id=ctx.org_id,
        reviewer_id=ctx.user_id, outcome="approved", note=payload.note,
    )
    if a is None:
        exists = await db.scalar(select(ToolApproval.id).where(
            ToolApproval.id == approval_id, ToolApproval.organization_id == ctx.org_id,
        ))
        raise HTTPException(
            status_code=409 if exists else 404,
            detail="Approval already decided" if exists else "Approval request not found",
        )
    await db.commit()
    return await _approval_out(db, a)


@router.post("/tool-approvals/{approval_id}/reject")
async def reject_tool(
    approval_id: int,
    payload: ApprovalReview,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    a = await transition_approval(
        db, approval_id=approval_id, organization_id=ctx.org_id,
        reviewer_id=ctx.user_id, outcome="rejected", note=payload.note,
    )
    if a is None:
        exists = await db.scalar(select(ToolApproval.id).where(
            ToolApproval.id == approval_id, ToolApproval.organization_id == ctx.org_id,
        ))
        raise HTTPException(
            status_code=409 if exists else 404,
            detail="Approval already decided" if exists else "Approval request not found",
        )
    await db.commit()
    return await _approval_out(db, a)


# ── Alert rules ───────────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    event_type: str | None = Field(default=None, max_length=64)
    condition: dict[str, Any]
    severity: Severity = Severity.MEDIUM
    project_id: int | None = None
    agent_id: int | None = None


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    event_type: str | None = Field(default=None, max_length=64)
    condition: dict[str, Any] | None = None
    severity: Severity | None = None
    status: AlertRuleStatus | None = None
    project_id: int | None = None
    agent_id: int | None = None


class IncidentResolution(BaseModel):
    note: str | None = Field(default=None, max_length=2000)

@router.get("/alerts/rules")
async def list_alert_rules(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    rules = await alerts_svc.list_rules(db, ctx.org_id)
    return {"items": [_rule_out(r) for r in rules]}


@router.post("/alerts/rules", status_code=201)
async def create_alert_rule(
    payload: AlertRuleCreate,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    try:
        rule = await alerts_svc.create_rule(
            db, ctx.org_id, payload.model_dump(mode="json"), created_by_id=ctx.user_id
        )
    except alerts_svc.AlertRuleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return _rule_out(rule)


@router.patch("/alerts/rules/{rule_id}")
async def update_alert_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    try:
        rule = await alerts_svc.update_rule(
            db, rule_id, ctx.org_id, payload.model_dump(mode="json", exclude_unset=True),
            user_id=ctx.user_id,
        )
    except alerts_svc.AlertRuleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.commit()
    return _rule_out(rule)


@router.delete("/alerts/rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: int,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    deleted = await alerts_svc.delete_rule(db, rule_id, ctx.org_id, user_id=ctx.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.commit()


# ── Alert incidents ───────────────────────────────────────────────────────────

@router.get("/alerts/incidents")
async def list_alert_incidents(
    status: AlertIncidentStatus | None = Query(default=None),
    severity: Severity | None = Query(default=None),
    rule_id: int | None = Query(default=None),
    event_type: str | None = Query(default=None, max_length=64),
    project_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    incidents = await alerts_svc.list_incidents(
        db, ctx.org_id,
        status=status.value if status else None,
        severity=severity.value if severity else None,
        rule_id=rule_id,
        event_type=event_type,
        project_id=project_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return {"items": [await _incident_out(db, item) for item in incidents]}


@router.get("/alerts/incidents/{incident_id}")
async def get_alert_incident(
    incident_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    incident = await alerts_svc.get_incident(db, incident_id, ctx.org_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return await _incident_out(db, incident)


async def _transition_alert_incident(
    db: AsyncSession,
    ctx: OrgContext,
    incident_id: int,
    outcome: str,
    note: str | None = None,
):
    incident, error = await alerts_svc.transition_incident(
        db, incident_id, ctx.org_id, outcome, ctx.user_id, note
    )
    if error:
        raise HTTPException(
            status_code=404 if error == "not_found" else 409,
            detail="Incident not found" if error == "not_found" else "Invalid incident transition",
        )
    await db.commit()
    return await _incident_out(db, incident)


@router.post("/alerts/incidents/{incident_id}/acknowledge")
async def acknowledge_alert_incident(
    incident_id: int,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    return await _transition_alert_incident(db, ctx, incident_id, "ACKNOWLEDGED")


@router.post("/alerts/incidents/{incident_id}/resolve")
async def resolve_alert_incident(
    incident_id: int,
    payload: IncidentResolution,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    return await _transition_alert_incident(
        db, ctx, incident_id, "RESOLVED", payload.note
    )


@router.patch("/alerts/incidents/{incident_id}")
async def update_alert_incident(
    incident_id: int,
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    outcome = payload.get("status")
    if outcome not in {"ACKNOWLEDGED", "RESOLVED"}:
        raise HTTPException(status_code=422, detail="Unsupported incident status")
    return await _transition_alert_incident(
        db, ctx, incident_id, outcome, payload.get("note")
    )


# ── Serialisers ───────────────────────────────────────────────────────────────

def _finding_out(f: SecurityFinding) -> dict:
    return {
        "id": f.id,
        "organization_id": f.organization_id,
        "trace_id": f.trace_id,
        "span_id": f.span_id,
        "agent_id": f.agent_id,
        "finding_type": f.finding_type,
        "severity": f.severity,
        "title": f.title,
        "description": f.description,
        "evidence": f.evidence,
        "action_taken": f.action_taken,
        "redacted_content": f.redacted_content,
        "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
        "resolved_by_id": f.resolved_by_id,
        "resolution_note": f.resolution_note,
        "created_at": f.created_at.isoformat(),
    }


def _policy_out(p: AgentPolicy) -> dict:
    return {
        "id": p.id,
        "organization_id": p.organization_id,
        "agent_id": p.agent_id,
        "allowed_tools": p.allowed_tools,
        "blocked_tools": p.blocked_tools,
        "tools_requiring_approval": p.tools_requiring_approval,
        "max_tokens_per_trace": p.max_tokens_per_trace,
        "max_cost_per_trace_usd": p.max_cost_per_trace_usd,
        "allowed_domains": p.allowed_domains,
        "blocked_domains": p.blocked_domains,
        "capture_inputs": p.capture_inputs,
        "capture_outputs": p.capture_outputs,
        "pii_action": p.pii_action,
        "secret_action": p.secret_action,
        "injection_action": p.injection_action,
        "active": p.active,
        "created_at": p.created_at.isoformat(),
    }


async def _approval_out(db: AsyncSession, a: ToolApproval) -> dict:
    trace = await db.scalar(select(Trace).where(Trace.id == a.trace_id)) if a.trace_id else None
    agent = await db.scalar(select(Agent).where(Agent.id == a.agent_id)) if a.agent_id else None
    return {
        "id": a.id,
        "organization_id": a.organization_id,
        "trace_id": a.trace_id,
        "span_id": a.span_id,
        "agent_id": a.agent_id,
        "agent_name": agent.name if agent else None,
        "external_request_id": a.external_request_id,
        "tool_name": a.tool_name,
        "approval_context": a.tool_input,
        "target_url": a.target_url,
        "trace_name": trace.name if trace else None,
        "external_trace_id": trace.external_trace_id if trace else None,
        "status": "used" if a.used_at is not None else a.status,
        "review_note": a.review_note,
        "reviewed_by_id": a.reviewed_by_id,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "used_at": a.used_at.isoformat() if a.used_at else None,
        "created_at": a.created_at.isoformat(),
    }


def _rule_out(r: AlertRule) -> dict:
    return {
        "id": r.id,
        "organization_id": r.organization_id,
        "project_id": r.project_id,
        "agent_id": r.agent_id,
        "name": r.name,
        "description": r.description,
        "event_type": r.event_type,
        "condition": r.condition,
        "severity": r.severity,
        "status": r.status,
        "notification_channels": r.notification_channels,
        "created_at": r.created_at.isoformat(),
    }


async def _incident_out(db: AsyncSession, i: AlertIncident) -> dict:
    rule = await db.scalar(select(AlertRule).where(AlertRule.id == i.rule_id))
    trace = await db.scalar(select(Trace).where(Trace.id == i.trace_id)) if i.trace_id else None
    agent = await db.scalar(select(Agent).where(Agent.id == i.agent_id)) if i.agent_id else None
    return {
        "id": i.id,
        "rule_id": i.rule_id,
        "rule_name": rule.name if rule else None,
        "event_type": i.event_type,
        "source_type": i.source_type,
        "source_id": i.source_id,
        "trace_id": i.trace_id,
        "external_trace_id": trace.external_trace_id if trace else None,
        "project_id": i.project_id,
        "agent_id": i.agent_id,
        "agent_name": agent.name if agent else None,
        "severity": i.severity,
        "status": i.status,
        "triggered_at": i.triggered_at.isoformat(),
        "acknowledged_at": i.acknowledged_at.isoformat() if i.acknowledged_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "context": i.context,
        "resolution_note": i.resolution_note,
        "acknowledged_by_id": i.acknowledged_by_id,
        "resolved_by_id": i.resolved_by_id,
    }
