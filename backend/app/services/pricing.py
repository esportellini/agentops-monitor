"""
Pricing service.

All cost calculations go through this module — never hardcode prices anywhere else.
Lookup resolves the correct pricing row for the call timestamp, supporting
price history with effective_from / effective_to windows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import ModelPricing


def _usd(tokens: int, price_per_million: float) -> Decimal:
    """Calculate cost in USD. Returns Decimal for precision."""
    return Decimal(str(price_per_million)) * Decimal(tokens) / Decimal("1_000_000")


async def get_pricing(
    db: AsyncSession,
    provider: str,
    model: str,
    at: datetime | None = None,
) -> ModelPricing | None:
    """
    Return the active pricing row for provider+model at a given time.

    Matching rule:
      effective_from <= at AND (effective_to IS NULL OR effective_to > at)
    If multiple rows match (shouldn't happen with correct data), the one
    with the most recent effective_from wins.
    """
    when = at or datetime.now(timezone.utc)

    result = await db.execute(
        select(ModelPricing)
        .where(
            and_(
                ModelPricing.provider == provider,
                ModelPricing.model == model,
                ModelPricing.active == True,  # noqa: E712
                ModelPricing.effective_from <= when,
                or_(
                    ModelPricing.effective_to == None,  # noqa: E711
                    ModelPricing.effective_to > when,
                ),
            )
        )
        .order_by(ModelPricing.effective_from.desc())
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
        _usd(input_tokens, float(pricing.input_price_per_million))
        + _usd(output_tokens, float(pricing.output_price_per_million))
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
    Compute cost for a model call, looking up the correct pricing row.
    Returns Decimal("0") if no pricing is configured for this provider+model.
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
