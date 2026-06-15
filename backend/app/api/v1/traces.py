from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import OrgContext, require_analyst, require_org_member
from app.db.session import get_db
from app.models.trace import ModelCall, Span, ToolCall, Trace, TraceEvent
from app.repositories import trace as trace_repo
from sqlalchemy import select

router = APIRouter(prefix="/organizations/{org_id}/traces", tags=["traces"])


@router.get("")
async def list_traces(
    project_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    environment_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    traces, total = await trace_repo.list_traces(
        db,
        ctx.org_id,
        project_id=project_id,
        agent_id=agent_id,
        environment_id=environment_id,
        status=status,
        risk_level=risk_level,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "items": [_trace_summary(t) for t in traces],
    }


@router.get("/{trace_id}")
async def get_trace(
    trace_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Trace)
        .where(Trace.id == trace_id, Trace.organization_id == ctx.org_id)
        .options(
            selectinload(Trace.spans).selectinload(Span.tool_calls),
            selectinload(Trace.spans).selectinload(Span.model_calls),
            selectinload(Trace.events),
            selectinload(Trace.cost_records),
        )
    )
    trace = result.scalar_one_or_none()
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    return _trace_detail(trace)


def _trace_summary(t: Trace) -> dict:
    return {
        "id": t.id,
        "external_trace_id": t.external_trace_id,
        "name": t.name,
        "status": t.status,
        "risk_level": t.risk_level,
        "project_id": t.project_id,
        "agent_id": t.agent_id,
        "environment_id": t.environment_id,
        "started_at": t.started_at.isoformat(),
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "duration_ms": t.duration_ms,
        "total_input_tokens": t.total_input_tokens,
        "total_output_tokens": t.total_output_tokens,
        "total_cost": float(t.total_cost),
        "session_id": t.session_id,
    }


def _span_detail(s: Span) -> dict:
    return {
        "id": s.id,
        "external_span_id": s.external_span_id,
        "parent_span_id": s.parent_span_id,
        "name": s.name,
        "type": s.type,
        "status": s.status,
        "started_at": s.started_at.isoformat(),
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "duration_ms": s.duration_ms,
        "input_data": s.input_data,
        "output_data": s.output_data,
        "error_data": s.error_data,
        "metadata": s.metadata_,
        "tool_calls": [
            {
                "id": tc.id,
                "tool_name": tc.tool_name,
                "input_data": tc.input_data,
                "output_data": tc.output_data,
                "status": tc.status,
                "duration_ms": tc.duration_ms,
                "requires_approval": tc.requires_approval,
                "blocked_reason": tc.blocked_reason,
            }
            for tc in s.tool_calls
        ],
        "model_calls": [
            {
                "id": mc.id,
                "provider": mc.provider,
                "model": mc.model,
                "input_tokens": mc.input_tokens,
                "output_tokens": mc.output_tokens,
                "estimated_cost": float(mc.estimated_cost),
                "latency_ms": mc.latency_ms,
                "temperature": mc.temperature,
                "status": mc.status,
            }
            for mc in s.model_calls
        ],
    }


def _trace_detail(t: Trace) -> dict:
    spans = sorted(t.spans, key=lambda s: s.started_at)
    return {
        **_trace_summary(t),
        "metadata": t.metadata_,
        "user_reference": t.user_reference,
        "spans": [_span_detail(s) for s in spans],
        "events": [
            {
                "id": e.id,
                "span_id": e.span_id,
                "event_type": e.event_type,
                "severity": e.severity,
                "message": e.message,
                "metadata": e.metadata_,
                "created_at": e.created_at.isoformat(),
            }
            for e in sorted(t.events, key=lambda e: e.created_at)
        ],
        "cost_records": [
            {
                "id": cr.id,
                "provider": cr.provider,
                "model": cr.model,
                "input_tokens": cr.input_tokens,
                "output_tokens": cr.output_tokens,
                "cost_usd": float(cr.cost_usd),
                "recorded_at": cr.recorded_at.isoformat(),
            }
            for cr in t.cost_records
        ],
    }
