from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_analyst, require_org_member
from app.db.session import get_db
from app.models.pricing import ModelPricing
from app.services import metrics as metrics_svc
from app.services.pricing import (
    has_pricing_overlap,
    list_pricing_for_organization,
    normalize_provider_model,
)
from sqlalchemy import select

router = APIRouter(prefix="/organizations/{org_id}", tags=["metrics"])

_DEFAULT_DAYS = 30


class PricingCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    input_price_per_million: Decimal = Field(ge=0)
    output_price_per_million: Decimal = Field(ge=0)
    effective_from: datetime
    effective_to: datetime | None = None
    active: bool = True

    @model_validator(mode="after")
    def validate_window(self):
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class PricingUpdate(BaseModel):
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    active: bool | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_window(
    since: str | None,
    until: str | None,
    days: int = _DEFAULT_DAYS,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end = datetime.fromisoformat(until) if until else now
    start = datetime.fromisoformat(since) if since else (end - timedelta(days=days))
    return start, end


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get("/metrics/overview")
async def metrics_overview(
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    start, end = _parse_window(since, until)
    return await metrics_svc.get_overview(db, ctx.org_id, since=start, until=end)


# ── Timeseries ────────────────────────────────────────────────────────────────

@router.get("/metrics/timeseries")
async def metrics_timeseries(
    days: int = Query(default=30, ge=1, le=365),
    granularity: str = Query(default="day", pattern="^(hour|day|week|month)$"),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await metrics_svc.get_timeseries(db, ctx.org_id, days=days, granularity=granularity)


# ── Agents ────────────────────────────────────────────────────────────────────

@router.get("/metrics/agents")
async def metrics_agents(
    days: int = Query(default=30, ge=1, le=365),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await metrics_svc.get_agent_metrics(db, ctx.org_id, days=days)


# ── Models ────────────────────────────────────────────────────────────────────

@router.get("/metrics/models")
async def metrics_models(
    days: int = Query(default=30, ge=1, le=365),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await metrics_svc.get_model_metrics(db, ctx.org_id, days=days)


# ── Projects ──────────────────────────────────────────────────────────────────

@router.get("/metrics/projects")
async def metrics_projects(
    days: int = Query(default=30, ge=1, le=365),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await metrics_svc.get_project_metrics(db, ctx.org_id, days=days)


# ── Costs ─────────────────────────────────────────────────────────────────────

@router.get("/costs")
async def costs(
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    project_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    environment_id: int | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    start, end = _parse_window(since, until)
    return await metrics_svc.get_cost_summary(
        db,
        ctx.org_id,
        since=start,
        until=end,
        project_id=project_id,
        agent_id=agent_id,
        environment_id=environment_id,
        provider=provider,
        model=model,
    )


@router.get("/costs/projection")
async def costs_projection(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await metrics_svc.get_cost_projection(db, ctx.org_id)


@router.get("/costs/expensive-traces")
async def expensive_traces(
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    start, end = _parse_window(since, until)
    summary = await metrics_svc.get_cost_summary(db, ctx.org_id, since=start, until=end)
    return {"traces": summary["top_expensive_traces"][:limit]}


# ── Pricing CRUD ──────────────────────────────────────────────────────────────

@router.get("/pricing")
async def list_pricing(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_pricing_for_organization(db, ctx.org_id)
    return {"items": [_pricing_out(r) for r in rows]}


@router.post("/pricing", status_code=201)
async def create_pricing(
    body: PricingCreate,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    provider, model = normalize_provider_model(body.provider, body.model)
    if body.active and await has_pricing_overlap(
        db,
        organization_id=ctx.org_id,
        provider=provider,
        model=model,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    ):
        raise HTTPException(status_code=409, detail="Pricing window overlaps an active row")

    pricing = ModelPricing(
        organization_id=ctx.org_id,
        provider=provider,
        model=model,
        input_price_per_million=body.input_price_per_million,
        output_price_per_million=body.output_price_per_million,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        active=body.active,
    )
    db.add(pricing)
    await db.commit()
    await db.refresh(pricing)
    return _pricing_out(pricing)


@router.patch("/pricing/{pricing_id}")
async def update_pricing(
    pricing_id: int,
    body: PricingUpdate,
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ModelPricing).where(
            ModelPricing.id == pricing_id,
            ModelPricing.organization_id == ctx.org_id,
        )
    )
    pricing = result.scalar_one_or_none()
    if not pricing:
        raise HTTPException(status_code=404, detail="Pricing not found")

    updates = body.model_dump(exclude_unset=True)
    effective_from = _as_utc(updates.get("effective_from", pricing.effective_from))
    effective_to = _as_utc(updates.get("effective_to", pricing.effective_to))
    active = updates.get("active", pricing.active)
    if effective_to is not None and effective_to <= effective_from:
        raise HTTPException(status_code=422, detail="effective_to must be after effective_from")
    if active and await has_pricing_overlap(
        db,
        organization_id=ctx.org_id,
        provider=pricing.provider,
        model=pricing.model,
        effective_from=effective_from,
        effective_to=effective_to,
        exclude_id=pricing.id,
    ):
        raise HTTPException(status_code=409, detail="Pricing window overlaps an active row")

    for field, value in updates.items():
        setattr(pricing, field, value)

    await db.commit()
    await db.refresh(pricing)
    return _pricing_out(pricing)


def _pricing_out(p: ModelPricing) -> dict:
    return {
        "id": p.id,
        "organization_id": p.organization_id,
        "provider": p.provider,
        "model": p.model,
        "input_price_per_million": float(p.input_price_per_million),
        "output_price_per_million": float(p.output_price_per_million),
        "effective_from": p.effective_from.isoformat(),
        "effective_to": p.effective_to.isoformat() if p.effective_to else None,
        "active": p.active,
    }
