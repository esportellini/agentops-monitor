"""
Metrics service.

All aggregations use SQL GROUP BY / SUM / COUNT — no Python-side accumulation.
Every query is scoped to organization_id to prevent cross-tenant data leakage.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, cast, Date, func, literal, Numeric, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trace import CostRecord, ModelCall, Span, Trace, TraceEvent
from app.models.project import Agent, Project, Environment
from app.models.enums import TraceStatus
from app.services.pricing import PRICED, UNPRICED


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ── Overview ──────────────────────────────────────────────────────────────────

async def get_overview(
    db: AsyncSession,
    organization_id: int,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """
    High-level KPIs for the dashboard header cards.
    All numbers scoped to the given time window (default: last 30 days).
    """
    until = until or _now()
    since = since or (until - timedelta(days=30))
    today_start = _day_start(until.date())

    # Trace-level aggregations
    trace_q = (
        select(
            func.count().label("total"),
            func.sum(case((Trace.status == TraceStatus.SUCCESS, 1), else_=0)).label("success"),
            func.sum(case((Trace.status == TraceStatus.ERROR, 1), else_=0)).label("errors"),
            func.sum(case((Trace.status == TraceStatus.BLOCKED, 1), else_=0)).label("blocked"),
            func.avg(Trace.duration_ms).label("avg_latency_ms"),
            func.sum(Trace.total_input_tokens).label("total_input_tokens"),
            func.sum(Trace.total_output_tokens).label("total_output_tokens"),
            func.coalesce(func.sum(cast(Trace.total_cost, Numeric(14, 8))), 0).label("total_cost"),
        )
        .where(
            Trace.organization_id == organization_id,
            Trace.started_at >= since,
            Trace.started_at < until,
        )
    )
    row = (await db.execute(trace_q)).one()

    # Today's cost
    today_cost_q = select(
        func.coalesce(func.sum(CostRecord.cost_usd), 0)
    ).where(
        CostRecord.organization_id == organization_id,
        CostRecord.recorded_at >= today_start,
        CostRecord.pricing_status == PRICED,
    )
    today_cost = (await db.execute(today_cost_q)).scalar_one()

    # Month-to-date cost
    month_start = _day_start(date(until.year, until.month, 1))
    mtd_cost_q = select(
        func.coalesce(func.sum(CostRecord.cost_usd), 0)
    ).where(
        CostRecord.organization_id == organization_id,
        CostRecord.recorded_at >= month_start,
        CostRecord.pricing_status == PRICED,
    )
    mtd_cost = (await db.execute(mtd_cost_q)).scalar_one()

    # Active agents (had a trace in the window)
    active_agents_q = select(func.count(func.distinct(Trace.agent_id))).where(
        Trace.organization_id == organization_id,
        Trace.agent_id != None,
        Trace.started_at >= since,
    )
    active_agents = (await db.execute(active_agents_q)).scalar_one()

    unpriced_q = select(func.count()).where(
        CostRecord.organization_id == organization_id,
        CostRecord.recorded_at >= since,
        CostRecord.recorded_at < until,
        CostRecord.pricing_status == UNPRICED,
    )
    unpriced_model_calls = int((await db.execute(unpriced_q)).scalar_one())

    # Today executions
    today_q = select(func.count()).where(
        Trace.organization_id == organization_id,
        Trace.started_at >= today_start,
    )
    today_count = (await db.execute(today_q)).scalar_one()

    total = row.total or 1  # avoid division by zero
    success_rate = round(float(row.success or 0) / total * 100, 1)

    # Monthly projection based on daily average
    days_elapsed = max((until - month_start).days, 1)
    days_in_month = 30  # approximation
    monthly_projection = float(mtd_cost) * days_in_month / days_elapsed

    return {
        "period": {"since": since.isoformat(), "until": until.isoformat()},
        "executions_total": int(row.total or 0),
        "executions_today": int(today_count or 0),
        "success_rate": success_rate,
        "errors": int(row.errors or 0),
        "blocked": int(row.blocked or 0),
        "avg_latency_ms": round(float(row.avg_latency_ms or 0)),
        "total_input_tokens": int(row.total_input_tokens or 0),
        "total_output_tokens": int(row.total_output_tokens or 0),
        "cost_today_usd": float(today_cost),
        "cost_mtd_usd": float(mtd_cost),
        "cost_projection_usd": round(monthly_projection, 4),
        "active_agents": int(active_agents or 0),
        "unpriced_model_calls": unpriced_model_calls,
    }


# ── Timeseries ────────────────────────────────────────────────────────────────

async def get_timeseries(
    db: AsyncSession,
    organization_id: int,
    *,
    days: int = 30,
    granularity: str = "day",
) -> list[dict[str, Any]]:
    """
    Daily (or hourly) bucketed metrics for chart rendering.
    Returns one row per bucket with executions, success_rate, cost, avg_latency.
    """
    since = _now() - timedelta(days=days)

    # Use PostgreSQL date_trunc for server-side bucketing
    bucket = func.date_trunc(granularity, Trace.started_at).label("bucket")

    q = (
        select(
            bucket,
            func.count().label("executions"),
            func.sum(case((Trace.status == TraceStatus.SUCCESS, 1), else_=0)).label("success"),
            func.sum(case((Trace.status == TraceStatus.ERROR, 1), else_=0)).label("errors"),
            func.avg(Trace.duration_ms).label("avg_latency_ms"),
            func.sum(Trace.total_input_tokens).label("input_tokens"),
            func.sum(Trace.total_output_tokens).label("output_tokens"),
        )
        .where(
            Trace.organization_id == organization_id,
            Trace.started_at >= since,
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    trace_rows = (await db.execute(q)).all()

    # Cost timeseries (from cost_records for accuracy)
    cost_bucket = func.date_trunc(granularity, CostRecord.recorded_at).label("bucket")
    cost_q = (
        select(cost_bucket, func.sum(CostRecord.cost_usd).label("cost"))
        .where(
            CostRecord.organization_id == organization_id,
            CostRecord.recorded_at >= since,
            CostRecord.pricing_status == PRICED,
        )
        .group_by(cost_bucket)
        .order_by(cost_bucket)
    )
    cost_rows = {r.bucket: float(r.cost) for r in (await db.execute(cost_q)).all()}

    result = []
    for r in trace_rows:
        execs = int(r.executions or 0)
        result.append({
            "bucket": r.bucket.isoformat(),
            "executions": execs,
            "success": int(r.success or 0),
            "errors": int(r.errors or 0),
            "success_rate": round(float(r.success or 0) / max(execs, 1) * 100, 1),
            "avg_latency_ms": round(float(r.avg_latency_ms or 0)),
            "input_tokens": int(r.input_tokens or 0),
            "output_tokens": int(r.output_tokens or 0),
            "cost_usd": cost_rows.get(r.bucket, 0.0),
        })
    return result


# ── Agent metrics ─────────────────────────────────────────────────────────────

async def get_agent_metrics(
    db: AsyncSession,
    organization_id: int,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    since = _now() - timedelta(days=days)

    q = (
        select(
            Trace.agent_id,
            Agent.name.label("agent_name"),
            func.count().label("executions"),
            func.sum(case((Trace.status == TraceStatus.SUCCESS, 1), else_=0)).label("success"),
            func.sum(case((Trace.status == TraceStatus.ERROR, 1), else_=0)).label("errors"),
            func.avg(Trace.duration_ms).label("avg_latency_ms"),
            func.sum(Trace.total_cost).label("total_cost"),
            func.avg(Trace.total_cost).label("avg_cost_per_execution"),
            func.sum(Trace.unpriced_model_calls).label("unpriced_model_calls"),
        )
        .join(Agent, Agent.id == Trace.agent_id, isouter=True)
        .where(
            Trace.organization_id == organization_id,
            Trace.started_at >= since,
            Trace.agent_id != None,
        )
        .group_by(Trace.agent_id, Agent.name)
        .order_by(func.sum(Trace.total_cost).desc())
    )
    rows = (await db.execute(q)).all()

    return [
        {
            "agent_id": r.agent_id,
            "agent_name": r.agent_name or f"agent_{r.agent_id}",
            "executions": int(r.executions),
            "success": int(r.success or 0),
            "errors": int(r.errors or 0),
            "success_rate": round(float(r.success or 0) / max(int(r.executions), 1) * 100, 1),
            "avg_latency_ms": round(float(r.avg_latency_ms or 0)),
            "total_cost_usd": float(r.total_cost or 0),
            "avg_cost_per_execution_usd": float(r.avg_cost_per_execution or 0),
            "unpriced_model_calls": int(r.unpriced_model_calls or 0),
        }
        for r in rows
    ]


# ── Model metrics ─────────────────────────────────────────────────────────────

async def get_model_metrics(
    db: AsyncSession,
    organization_id: int,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    since = _now() - timedelta(days=days)

    # Join through Span → Trace to scope to org
    q = (
        select(
            ModelCall.provider,
            ModelCall.model,
            func.count().label("calls"),
            func.sum(ModelCall.input_tokens).label("input_tokens"),
            func.sum(ModelCall.output_tokens).label("output_tokens"),
            func.sum(
                case(
                    (ModelCall.pricing_status == PRICED, ModelCall.estimated_cost),
                    else_=0,
                )
            ).label("total_cost"),
            func.avg(ModelCall.latency_ms).label("avg_latency_ms"),
            func.avg(
                case(
                    (ModelCall.pricing_status == PRICED, ModelCall.estimated_cost),
                    else_=None,
                )
            ).label("avg_cost"),
            func.sum(
                case((ModelCall.pricing_status == UNPRICED, 1), else_=0)
            ).label("unpriced_calls"),
        )
        .join(Span, Span.id == ModelCall.span_id)
        .join(Trace, Trace.id == Span.trace_id)
        .where(
            Trace.organization_id == organization_id,
            Trace.started_at >= since,
        )
        .group_by(ModelCall.provider, ModelCall.model)
        .order_by(func.sum(ModelCall.estimated_cost).desc())
    )
    rows = (await db.execute(q)).all()

    return [
        {
            "provider": r.provider,
            "model": r.model,
            "calls": int(r.calls),
            "input_tokens": int(r.input_tokens or 0),
            "output_tokens": int(r.output_tokens or 0),
            "total_tokens": int((r.input_tokens or 0) + (r.output_tokens or 0)),
            "total_cost_usd": float(r.total_cost or 0),
            "avg_cost_per_call_usd": float(r.avg_cost or 0),
            "avg_latency_ms": round(float(r.avg_latency_ms or 0)) if r.avg_latency_ms else None,
            "unpriced_calls": int(r.unpriced_calls or 0),
        }
        for r in rows
    ]


# ── Project metrics ───────────────────────────────────────────────────────────

async def get_project_metrics(
    db: AsyncSession,
    organization_id: int,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    since = _now() - timedelta(days=days)

    q = (
        select(
            Trace.project_id,
            Project.name.label("project_name"),
            func.count().label("executions"),
            func.sum(case((Trace.status == TraceStatus.SUCCESS, 1), else_=0)).label("success"),
            func.sum(Trace.total_cost).label("total_cost"),
            func.avg(Trace.total_cost).label("avg_cost"),
            func.sum(Trace.unpriced_model_calls).label("unpriced_model_calls"),
        )
        .join(Project, Project.id == Trace.project_id, isouter=True)
        .where(
            Trace.organization_id == organization_id,
            Trace.started_at >= since,
        )
        .group_by(Trace.project_id, Project.name)
        .order_by(func.sum(Trace.total_cost).desc())
    )
    rows = (await db.execute(q)).all()

    return [
        {
            "project_id": r.project_id,
            "project_name": r.project_name or f"project_{r.project_id}",
            "executions": int(r.executions),
            "success": int(r.success or 0),
            "success_rate": round(float(r.success or 0) / max(int(r.executions), 1) * 100, 1),
            "total_cost_usd": float(r.total_cost or 0),
            "avg_cost_usd": float(r.avg_cost or 0),
            "unpriced_model_calls": int(r.unpriced_model_calls or 0),
        }
        for r in rows
    ]


# ── Cost breakdown ────────────────────────────────────────────────────────────

async def get_cost_summary(
    db: AsyncSession,
    organization_id: int,
    *,
    since: datetime,
    until: datetime,
    project_id: int | None = None,
    agent_id: int | None = None,
    environment_id: int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Cost breakdown for the /costs page with optional filters.
    """
    # Build base filter on traces
    trace_filters = [
        Trace.organization_id == organization_id,
        Trace.started_at >= since,
        Trace.started_at < until,
    ]
    if project_id:
        trace_filters.append(Trace.project_id == project_id)
    if agent_id:
        trace_filters.append(Trace.agent_id == agent_id)
    if environment_id:
        trace_filters.append(Trace.environment_id == environment_id)

    # Cost record filters (mirrors trace filters + model/provider)
    cr_filters = [
        CostRecord.organization_id == organization_id,
        CostRecord.recorded_at >= since,
        CostRecord.recorded_at < until,
    ]
    if provider:
        cr_filters.append(CostRecord.provider == provider)
    if model:
        cr_filters.append(CostRecord.model == model)
    if project_id or agent_id or environment_id:
        cr_filters.append(CostRecord.trace_id.in_(select(Trace.id).where(*trace_filters)))

    # Total cost
    total_cost_q = select(func.coalesce(func.sum(CostRecord.cost_usd), 0)).where(
        *cr_filters, CostRecord.pricing_status == PRICED
    )
    total_cost = float((await db.execute(total_cost_q)).scalar_one())
    unpriced_q = select(func.count()).where(
        *cr_filters, CostRecord.pricing_status == UNPRICED
    )
    unpriced_model_calls = int((await db.execute(unpriced_q)).scalar_one())

    # Total executions
    exec_q = select(func.count()).where(*trace_filters)
    total_executions = int((await db.execute(exec_q)).scalar_one())

    # Cost by model
    by_model_q = (
        select(
            CostRecord.provider,
            CostRecord.model,
            func.count().label("calls"),
            func.sum(CostRecord.input_tokens).label("input_tokens"),
            func.sum(CostRecord.output_tokens).label("output_tokens"),
            func.sum(
                case(
                    (CostRecord.pricing_status == PRICED, CostRecord.cost_usd),
                    else_=0,
                )
            ).label("cost"),
            func.sum(
                case((CostRecord.pricing_status == UNPRICED, 1), else_=0)
            ).label("unpriced_calls"),
        )
        .where(*cr_filters)
        .group_by(CostRecord.provider, CostRecord.model)
        .order_by(func.sum(CostRecord.cost_usd).desc())
    )
    by_model = [
        {
            "provider": r.provider,
            "model": r.model,
            "calls": int(r.calls),
            "input_tokens": int(r.input_tokens or 0),
            "output_tokens": int(r.output_tokens or 0),
            "cost_usd": float(r.cost or 0),
            "unpriced_calls": int(r.unpriced_calls or 0),
        }
        for r in (await db.execute(by_model_q)).all()
    ]

    # Top expensive traces
    top_traces_q = (
        select(
            Trace.id,
            Trace.external_trace_id,
            Trace.name,
            Trace.status,
            Trace.started_at,
            Trace.duration_ms,
            Trace.total_cost,
            Trace.total_input_tokens,
            Trace.total_output_tokens,
            Trace.unpriced_model_calls,
        )
        .where(*trace_filters)
        .order_by(Trace.total_cost.desc())
        .limit(20)
    )
    top_traces = [
        {
            "id": r.id,
            "external_trace_id": r.external_trace_id,
            "name": r.name,
            "status": r.status,
            "started_at": r.started_at.isoformat(),
            "duration_ms": r.duration_ms,
            "total_cost_usd": float(r.total_cost or 0),
            "total_tokens": int((r.total_input_tokens or 0) + (r.total_output_tokens or 0)),
            "unpriced_model_calls": int(r.unpriced_model_calls or 0),
        }
        for r in (await db.execute(top_traces_q)).all()
    ]

    # Monthly projection from daily average
    days = max((until - since).days, 1)
    daily_avg = total_cost / days
    days_in_month = 30
    projection = daily_avg * days_in_month

    avg_cost_per_execution = total_cost / max(total_executions, 1)

    return {
        "period": {"since": since.isoformat(), "until": until.isoformat()},
        "total_cost_usd": total_cost,
        "total_executions": total_executions,
        "unpriced_model_calls": unpriced_model_calls,
        "avg_cost_per_execution_usd": avg_cost_per_execution,
        "monthly_projection_usd": round(projection, 4),
        "cost_by_model": by_model,
        "top_expensive_traces": top_traces,
    }


async def get_cost_projection(
    db: AsyncSession,
    organization_id: int,
) -> dict[str, Any]:
    """Monthly projection based on last 7 days of spend."""
    now = _now()
    week_ago = now - timedelta(days=7)

    week_cost_q = select(func.coalesce(func.sum(CostRecord.cost_usd), 0)).where(
        CostRecord.organization_id == organization_id,
        CostRecord.recorded_at >= week_ago,
        CostRecord.pricing_status == PRICED,
    )
    week_cost = float((await db.execute(week_cost_q)).scalar_one())
    daily_avg = week_cost / 7

    # Month-to-date
    month_start = _day_start(date(now.year, now.month, 1))
    mtd_q = select(func.coalesce(func.sum(CostRecord.cost_usd), 0)).where(
        CostRecord.organization_id == organization_id,
        CostRecord.recorded_at >= month_start,
        CostRecord.pricing_status == PRICED,
    )
    mtd_cost = float((await db.execute(mtd_q)).scalar_one())

    # Days remaining in month
    import calendar
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    days_elapsed = now.day
    days_remaining = days_in_month - days_elapsed
    projected_remaining = daily_avg * days_remaining
    projected_total = mtd_cost + projected_remaining

    return {
        "daily_avg_usd": round(daily_avg, 6),
        "mtd_cost_usd": round(mtd_cost, 6),
        "projected_month_total_usd": round(projected_total, 4),
        "projected_remaining_usd": round(projected_remaining, 4),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
    }
