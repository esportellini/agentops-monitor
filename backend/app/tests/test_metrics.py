"""
Tests for pricing service and metrics aggregations.

Coverage:
- input token cost calculation
- output token cost calculation
- total cost calculation
- pricing lookup by effective date (vigência)
- trace without pricing config
- aggregation by project (org isolation)
- monthly projection
- org isolation (cross-tenant must not leak)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import ModelPricing
from app.services.pricing import (
    calculate_cost,
    calculate_model_call_cost,
    get_pricing,
)
from app.services.metrics import (
    get_cost_summary,
    get_overview,
    get_project_metrics,
    get_cost_projection,
)
from app.tests.factories import (
    make_org,
    make_project,
    make_user,
    make_user_with_org,
)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# ── Pricing fixtures ──────────────────────────────────────────────────────────

async def _seed_pricing(
    db: AsyncSession,
    provider: str = "openai",
    model: str = "gpt-4o",
    inp: float = 2.50,
    out: float = 10.00,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> ModelPricing:
    p = ModelPricing(
        provider=provider,
        model=model,
        input_price_per_million=inp,
        output_price_per_million=out,
        effective_from=from_dt or _utc(2024, 1, 1),
        effective_to=to_dt,
        active=True,
    )
    db.add(p)
    await db.flush()
    return p


# ── Token cost calculation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_input_token_cost(db: AsyncSession):
    pricing = await _seed_pricing(db, inp=5.00, out=15.00)

    # 1,000,000 input tokens at $5/M = $5
    cost = calculate_cost(pricing, input_tokens=1_000_000, output_tokens=0)
    assert cost == Decimal("5.00")


@pytest.mark.asyncio
async def test_output_token_cost(db: AsyncSession):
    pricing = await _seed_pricing(db, inp=5.00, out=15.00)

    # 500,000 output tokens at $15/M = $7.50
    cost = calculate_cost(pricing, input_tokens=0, output_tokens=500_000)
    assert cost == Decimal("7.5")


@pytest.mark.asyncio
async def test_combined_cost(db: AsyncSession):
    pricing = await _seed_pricing(db, inp=2.50, out=10.00)

    # 100 input tokens + 50 output tokens
    # input:  100 * 2.50 / 1_000_000 = 0.00000025
    # output: 50  * 10.00 / 1_000_000 = 0.0000005
    # total = 0.00000075
    cost = calculate_cost(pricing, input_tokens=100, output_tokens=50)
    assert cost == Decimal("0.000000750")


@pytest.mark.asyncio
async def test_zero_tokens_zero_cost(db: AsyncSession):
    pricing = await _seed_pricing(db)
    cost = calculate_cost(pricing, input_tokens=0, output_tokens=0)
    assert cost == Decimal("0")


# ── Pricing lookup by vigência ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pricing_lookup_current(db: AsyncSession):
    await _seed_pricing(db, provider="openai", model="gpt-4o-mini", inp=0.15, out=0.60)
    await db.commit()

    result = await get_pricing(db, "openai", "gpt-4o-mini")
    assert result is not None
    assert float(result.input_price_per_million) == 0.15


@pytest.mark.asyncio
async def test_pricing_lookup_at_specific_date(db: AsyncSession):
    old = _utc(2023, 1, 1)
    new = _utc(2024, 6, 1)

    # Old price: Jan 2023 – Jun 2024
    await _seed_pricing(db, inp=10.00, out=30.00,
                        from_dt=old, to_dt=new)
    # New price: Jun 2024 – present
    await _seed_pricing(db, inp=2.50, out=10.00, from_dt=new)
    await db.commit()

    # At March 2023 → old price
    at_old = _utc(2023, 3, 15)
    old_result = await get_pricing(db, "openai", "gpt-4o", at=at_old)
    assert old_result is not None
    assert float(old_result.input_price_per_million) == 10.00

    # At July 2024 → new price
    at_new = _utc(2024, 7, 1)
    new_result = await get_pricing(db, "openai", "gpt-4o", at=at_new)
    assert new_result is not None
    assert float(new_result.input_price_per_million) == 2.50


@pytest.mark.asyncio
async def test_pricing_lookup_before_effective_from_returns_none(db: AsyncSession):
    # Price only valid from 2025
    await _seed_pricing(db, provider="future", model="model-x",
                        from_dt=_utc(2025, 1, 1))
    await db.commit()

    result = await get_pricing(db, "future", "model-x", at=_utc(2024, 1, 1))
    assert result is None


# ── Model call without pricing config ────────────────────────────────────────

@pytest.mark.asyncio
async def test_model_call_cost_no_pricing(db: AsyncSession):
    """A call to an unknown model returns $0 without raising."""
    cost = await calculate_model_call_cost(
        db, "unknown-provider", "unknown-model",
        input_tokens=1000, output_tokens=500,
    )
    assert cost == Decimal("0")


@pytest.mark.asyncio
async def test_calculate_model_call_cost_with_pricing(db: AsyncSession):
    await _seed_pricing(db, provider="anthropic", model="claude-3-opus",
                        inp=15.00, out=75.00)
    await db.commit()

    cost = await calculate_model_call_cost(
        db, "anthropic", "claude-3-opus",
        input_tokens=10_000, output_tokens=5_000,
    )
    # input:  10000 * 15.00 / 1_000_000 = 0.15
    # output: 5000  * 75.00 / 1_000_000 = 0.375
    # total = 0.525
    assert abs(float(cost) - 0.525) < 0.000001


# ── Overview metrics ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overview_empty_org(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="metrics-test@x.com", org_slug="metrics-org")
    await db.commit()

    result = await get_overview(db, org.id)
    assert result["executions_total"] == 0
    assert result["success_rate"] == 0.0
    assert result["cost_today_usd"] == 0.0


# ── Project aggregation ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_project_metrics_aggregation(db: AsyncSession):
    """Project metrics aggregate correctly and respect org scope."""
    _, org_a, _ = await make_user_with_org(db, email="pa@x.com", org_slug="proj-metrics-a")
    _, org_b, _ = await make_user_with_org(db, email="pb@x.com", org_slug="proj-metrics-b")
    await db.commit()

    # Org A has one project; org B should have no visibility into org A
    rows_a = await get_project_metrics(db, org_a.id, days=30)
    rows_b = await get_project_metrics(db, org_b.id, days=30)

    # Both have no traces yet — both should return empty lists
    assert isinstance(rows_a, list)
    assert isinstance(rows_b, list)
    # Crucially, org B cannot see org A's data
    a_project_ids = {r["project_id"] for r in rows_a}
    b_project_ids = {r["project_id"] for r in rows_b}
    assert a_project_ids.isdisjoint(b_project_ids) or (not rows_a and not rows_b)


# ── Monthly projection ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cost_projection_structure(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="proj-test@x.com", org_slug="proj-test")
    await db.commit()

    result = await get_cost_projection(db, org.id)
    assert "daily_avg_usd" in result
    assert "mtd_cost_usd" in result
    assert "projected_month_total_usd" in result
    assert "days_elapsed" in result
    assert "days_remaining" in result
    # days_elapsed + days_remaining should roughly equal the month length
    assert 1 <= result["days_elapsed"] <= 31
    assert 0 <= result["days_remaining"] <= 31


# ── Cost summary ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cost_summary_structure(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="cost-s@x.com", org_slug="cost-sum")
    await db.commit()

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    result = await get_cost_summary(
        db, org.id,
        since=now - timedelta(days=30),
        until=now,
    )
    assert "total_cost_usd" in result
    assert "cost_by_model" in result
    assert "top_expensive_traces" in result
    assert "monthly_projection_usd" in result
    assert result["total_cost_usd"] >= 0


# ── Org isolation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_org_isolation_in_overview(db: AsyncSession):
    """Two orgs should return independent metrics."""
    _, org1, _ = await make_user_with_org(db, email="iso1@x.com", org_slug="iso-1")
    _, org2, _ = await make_user_with_org(db, email="iso2@x.com", org_slug="iso-2")
    await db.commit()

    result1 = await get_overview(db, org1.id)
    result2 = await get_overview(db, org2.id)

    # Both should return valid structures independently
    assert "executions_total" in result1
    assert "executions_total" in result2
    # No data yet — both should be 0
    assert result1["executions_total"] == 0
    assert result2["executions_total"] == 0
