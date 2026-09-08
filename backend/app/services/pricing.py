"""
Pricing service.

All cost calculations go through this module — never hardcode prices anywhere else.
Lookup resolves the correct pricing row for the call timestamp, supporting
price history with effective_from / effective_to windows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import ModelPricing

PRICED = "PRICED"
UNPRICED = "UNPRICED"
USD_QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True)
class PricingResolution:
    status: str
    cost_usd: Decimal | None
    pricing: ModelPricing | None
    provider: str
    model: str
    occurred_at: datetime


def normalize_provider_model(provider: str, model: str) -> tuple[str, str]:
    """Apply the only safe normalization used by pricing and ingestion."""
    return provider.strip().lower(), model.strip()


def _decimal(value: Decimal | int | str | float) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _usd(tokens: int, price_per_million: Decimal | int | str | float) -> Decimal:
    """Calculate cost in USD. Returns Decimal for precision."""
    return _decimal(price_per_million) * Decimal(tokens) / Decimal("1000000")


async def get_pricing(
    db: AsyncSession,
    provider: str,
    model: str,
    at: datetime | None = None,
    organization_id: int | None = None,
) -> ModelPricing | None:
    """
    Return the active pricing row for provider+model at a given time.

    Matching rule:
      effective_from <= at AND (effective_to IS NULL OR effective_to > at)
    If multiple rows match (shouldn't happen with correct data), the one
    with the most recent effective_from wins.
    """
    when = at or datetime.now(timezone.utc)
    normalized_provider, normalized_model = normalize_provider_model(provider, model)

    scope_filter = (
        ModelPricing.organization_id.is_(None)
        if organization_id is None
        else or_(
            ModelPricing.organization_id == organization_id,
            ModelPricing.organization_id.is_(None),
        )
    )
    scope_priority = case(
        (ModelPricing.organization_id == organization_id, 0),
        else_=1,
    )

    result = await db.execute(
        select(ModelPricing)
        .where(
            and_(
                ModelPricing.provider == normalized_provider,
                ModelPricing.model == normalized_model,
                scope_filter,
                ModelPricing.active == True,  # noqa: E712
                ModelPricing.effective_from <= when,
                or_(
                    ModelPricing.effective_to == None,  # noqa: E711
                    ModelPricing.effective_to > when,
                ),
            )
        )
        .order_by(scope_priority, ModelPricing.effective_from.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def calculate_cost(
    pricing: ModelPricing,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Return total cost in USD given a pricing row and token counts."""
    return (
        _usd(input_tokens, pricing.input_price_per_million)
        + _usd(output_tokens, pricing.output_price_per_million)
    ).quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)


async def resolve_model_call_pricing(
    db: AsyncSession,
    *,
    organization_id: int,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    at: datetime | None = None,
) -> PricingResolution:
    """Resolve a model call to an explicit priced or unpriced result."""
    occurred_at = at or datetime.now(timezone.utc)
    normalized_provider, normalized_model = normalize_provider_model(provider, model)
    pricing = await get_pricing(
        db,
        normalized_provider,
        normalized_model,
        at=occurred_at,
        organization_id=organization_id,
    )
    if pricing is None:
        return PricingResolution(
            status=UNPRICED,
            cost_usd=None,
            pricing=None,
            provider=normalized_provider,
            model=normalized_model,
            occurred_at=occurred_at,
        )
    return PricingResolution(
        status=PRICED,
        cost_usd=calculate_cost(pricing, input_tokens, output_tokens),
        pricing=pricing,
        provider=normalized_provider,
        model=normalized_model,
        occurred_at=occurred_at,
    )


async def calculate_model_call_cost(
    db: AsyncSession,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    at: datetime | None = None,
) -> Decimal:
    """
    Compatibility helper for callers that only consume a numeric value.

    It returns Decimal("0") when pricing is absent and therefore must not be
    used for persistence or reporting, where that value would be ambiguous.
    Authoritative accounting uses ``resolve_model_call_pricing`` instead.
    """
    pricing = await get_pricing(db, provider, model, at=at)
    if pricing is None:
        return Decimal("0")
    return calculate_cost(pricing, input_tokens, output_tokens)


async def list_all_pricing(db: AsyncSession) -> list[ModelPricing]:
    result = await db.execute(
        select(ModelPricing).order_by(
            ModelPricing.provider,
            ModelPricing.model,
            ModelPricing.effective_from.desc(),
        )
    )
    return list(result.scalars().all())


async def list_pricing_for_organization(
    db: AsyncSession, organization_id: int
) -> list[ModelPricing]:
    result = await db.execute(
        select(ModelPricing)
        .where(
            or_(
                ModelPricing.organization_id == organization_id,
                ModelPricing.organization_id.is_(None),
            )
        )
        .order_by(
            ModelPricing.provider,
            ModelPricing.model,
            ModelPricing.organization_id.is_(None),
            ModelPricing.effective_from.desc(),
        )
    )
    return list(result.scalars().all())


async def has_pricing_overlap(
    db: AsyncSession,
    *,
    organization_id: int | None,
    provider: str,
    model: str,
    effective_from: datetime,
    effective_to: datetime | None,
    exclude_id: int | None = None,
) -> bool:
    """Return whether an active row intersects the proposed half-open window."""
    normalized_provider, normalized_model = normalize_provider_model(provider, model)
    scope = (
        ModelPricing.organization_id.is_(None)
        if organization_id is None
        else ModelPricing.organization_id == organization_id
    )
    filters = [
        scope,
        ModelPricing.provider == normalized_provider,
        ModelPricing.model == normalized_model,
        ModelPricing.active.is_(True),
        or_(ModelPricing.effective_to.is_(None), ModelPricing.effective_to > effective_from),
    ]
    if effective_to is not None:
        filters.append(ModelPricing.effective_from < effective_to)
    if exclude_id is not None:
        filters.append(ModelPricing.id != exclude_id)
    return (await db.scalar(select(ModelPricing.id).where(*filters).limit(1))) is not None
