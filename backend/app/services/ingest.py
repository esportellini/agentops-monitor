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

from sqlalchemy import func, select
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

log = get_logger(__name__)


class IngestError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(start: datetime, end: datetime) -> int:
    delta = end - start
    return max(0, int(delta.total_seconds() * 1000))


async def _validate_project_scope(ctx: IngestContext, project_id: int | None) -> int:
    """
    Return the resolved project_id, enforcing key scope.
    - If the key is project-scoped: project_id must match (or be omitted).
    - If the key is org-scoped: project_id is used as-is (or raises if None).
    """
    if ctx.project_id is not None:
        # Key is scoped to a specific project
        if project_id is not None and project_id != ctx.project_id:
            raise IngestError("API key is not authorized for this project", status_code=403)
        return ctx.project_id
    if project_id is None:
        raise IngestError("project_id is required for org-scoped keys", status_code=400)
    return project_id


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

    project_id = await _validate_project_scope(ctx, body.project_id)

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
        metadata_=body.metadata,
    )
    db.add(trace)
    await db.flush()
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
        # Idempotent: already finished
        return trace

    trace.status = body.status
    trace.ended_at = body.ended_at
    trace.duration_ms = _duration_ms(trace.started_at, body.ended_at)
    trace.risk_level = body.risk_level
    if body.metadata:
        trace.metadata_ = {**(trace.metadata_ or {}), **body.metadata}

    # Aggregate token and cost totals from all model calls in this trace
    agg = await db.execute(
        select(
            func.coalesce(func.sum(ModelCall.input_tokens), 0),
            func.coalesce(func.sum(ModelCall.output_tokens), 0),
            func.coalesce(func.sum(ModelCall.estimated_cost), 0),
        )
        .join(Span, Span.id == ModelCall.span_id)
        .where(Span.trace_id == trace.id)
    )
    row = agg.one()
    trace.total_input_tokens = int(row[0])
    trace.total_output_tokens = int(row[1])
    trace.total_cost = float(row[2])

    log.info(
        "ingest.trace.finished",
        trace_id=trace.id,
        status=body.status,
        duration_ms=trace.duration_ms,
        tokens_in=trace.total_input_tokens,
        tokens_out=trace.total_output_tokens,
        cost=trace.total_cost,
    )
    return trace


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
        input_data=body.input_data,
        output_data=body.output_data,
        error_data=body.error_data,
        metadata_=body.metadata,
    )
    db.add(span)
    await db.flush()
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

    if body.status is not None:
        span.status = body.status
    if body.ended_at is not None:
        span.ended_at = body.ended_at
        span.duration_ms = _duration_ms(span.started_at, body.ended_at)
    if body.output_data is not None:
        span.output_data = body.output_data
    if body.error_data is not None:
        span.error_data = body.error_data
    if body.metadata is not None:
        span.metadata_ = {**(span.metadata_ or {}), **body.metadata}

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

    tc = ToolCall(
        span_id=span.id,
        tool_name=body.tool_name,
        input_data=body.input_data,
        output_data=body.output_data,
        status=body.status,
        duration_ms=body.duration_ms,
        requires_approval=body.requires_approval,
        blocked_reason=body.blocked_reason,
    )
    db.add(tc)
    await db.flush()
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

    mc = ModelCall(
        span_id=span.id,
        provider=body.provider,
        model=body.model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        estimated_cost=body.estimated_cost,
        latency_ms=body.latency_ms,
        temperature=body.temperature,
        status=body.status,
    )
    db.add(mc)
    await db.flush()

    # Create a cost record for cost tracking
    if body.estimated_cost > 0:
        trace_result = await db.execute(
            select(Trace).where(Trace.id == span.trace_id)
        )
        trace = trace_result.scalar_one_or_none()
        if trace:
            cr = CostRecord(
                organization_id=trace.organization_id,
                trace_id=trace.id,
                model_call_id=mc.id,
                provider=body.provider,
                model=body.model,
                input_tokens=body.input_tokens,
                output_tokens=body.output_tokens,
                cost_usd=body.estimated_cost,
                recorded_at=_utcnow(),
            )
            db.add(cr)

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

    event = TraceEvent(
        trace_id=trace.id,
        span_id=span_db_id,
        event_type=body.event_type,
        severity=body.severity,
        message=body.message,
        metadata_=body.metadata,
        created_at=body.created_at or _utcnow(),
    )
    db.add(event)
    await db.flush()
    return event
