from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.trace import Span, Trace


async def get_trace_by_external_id(
    db: AsyncSession,
    external_trace_id: str,
    organization_id: int,
) -> Trace | None:
    result = await db.execute(
        select(Trace).where(
            Trace.external_trace_id == external_trace_id,
            Trace.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_trace_by_id(
    db: AsyncSession,
    trace_id: int,
    organization_id: int,
) -> Trace | None:
    result = await db.execute(
        select(Trace).where(
            Trace.id == trace_id,
            Trace.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_trace_with_spans(
    db: AsyncSession,
    trace_id: int,
    organization_id: int,
) -> Trace | None:
    result = await db.execute(
        select(Trace)
        .where(Trace.id == trace_id, Trace.organization_id == organization_id)
        .options(
            selectinload(Trace.spans).selectinload(Span.tool_calls),
            selectinload(Trace.spans).selectinload(Span.model_calls),
            selectinload(Trace.events),
            selectinload(Trace.cost_records),
        )
    )
    return result.scalar_one_or_none()


async def get_span_by_external_id(
    db: AsyncSession,
    external_span_id: str,
    trace_id: int,
) -> Span | None:
    result = await db.execute(
        select(Span).where(
            Span.external_span_id == external_span_id,
            Span.trace_id == trace_id,
        )
    )
    return result.scalar_one_or_none()


async def get_span_by_external_id_in_org(
    db: AsyncSession,
    external_span_id: str,
    organization_id: int,
) -> Span | None:
    """Used when we only know the span external ID, not the trace."""
    result = await db.execute(
        select(Span)
        .join(Trace, Trace.id == Span.trace_id)
        .where(
            Span.external_span_id == external_span_id,
            Trace.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_traces(
    db: AsyncSession,
    organization_id: int,
    *,
    project_id: int | None = None,
    agent_id: int | None = None,
    environment_id: int | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Trace], int]:
    from sqlalchemy import func
    from app.models.enums import TraceStatus, Severity

    q = select(Trace).where(Trace.organization_id == organization_id)

    if project_id:
        q = q.where(Trace.project_id == project_id)
    if agent_id:
        q = q.where(Trace.agent_id == agent_id)
    if environment_id:
        q = q.where(Trace.environment_id == environment_id)
    if status:
        q = q.where(Trace.status == TraceStatus(status))
    if risk_level:
        q = q.where(Trace.risk_level == Severity(risk_level))
    if search:
        q = q.where(
            Trace.external_trace_id.ilike(f"%{search}%") |
            Trace.name.ilike(f"%{search}%")
        )

    count_q = select(func.count()).select_from(q.subquery())
    count_result = await db.execute(count_q)
    total = count_result.scalar_one()

    q = q.order_by(Trace.started_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return list(result.scalars().all()), total
