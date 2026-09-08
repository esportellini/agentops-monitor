from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt import create_access_token
from app.models.enums import MemberRole
from app.models.pricing import ModelPricing
from app.tests.factories import make_user_with_org


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _pricing(*, organization_id: int | None, provider: str, model: str) -> ModelPricing:
    return ModelPricing(
        organization_id=organization_id,
        provider=provider,
        model=model,
        input_price_per_million=Decimal("1"),
        output_price_per_million=Decimal("2"),
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        active=True,
    )


@pytest.mark.asyncio
async def test_pricing_get_and_patch_are_tenant_isolated(
    client: AsyncClient, db: AsyncSession
):
    user_a, org_a, _ = await make_user_with_org(
        db, email="pricing-api-a@x.com", org_slug="pricing-api-a", role=MemberRole.OWNER
    )
    _, org_b, _ = await make_user_with_org(
        db, email="pricing-api-b@x.com", org_slug="pricing-api-b", role=MemberRole.OWNER
    )
    global_price = _pricing(
        organization_id=None, provider="api-isolation", model="global"
    )
    override_a = _pricing(
        organization_id=org_a.id, provider="api-isolation", model="override-a"
    )
    override_b = _pricing(
        organization_id=org_b.id, provider="api-isolation", model="override-b"
    )
    db.add_all([global_price, override_a, override_b])
    await db.commit()

    response = await client.get(
        f"/api/v1/organizations/{org_a.id}/pricing", headers=_headers(user_a.id)
    )
    ids = {item["id"] for item in response.json()["items"]}
    assert global_price.id in ids
    assert override_a.id in ids
    assert override_b.id not in ids

    for protected_id in (global_price.id, override_b.id):
        patch = await client.patch(
            f"/api/v1/organizations/{org_a.id}/pricing/{protected_id}",
            json={"input_price_per_million": "99"},
            headers=_headers(user_a.id),
        )
        assert patch.status_code == 404


@pytest.mark.asyncio
async def test_pricing_create_is_scoped_normalized_and_rejects_overlap(
    client: AsyncClient, db: AsyncSession
):
    user, org, _ = await make_user_with_org(
        db, email="pricing-overlap@x.com", org_slug="pricing-overlap", role=MemberRole.OWNER
    )
    headers = _headers(user.id)
    url = f"/api/v1/organizations/{org.id}/pricing"
    first = await client.post(url, headers=headers, json={
        "provider": " Test-Provider ",
        "model": " test-model ",
        "input_price_per_million": "2",
        "output_price_per_million": "6",
        "effective_from": "2026-01-01T00:00:00+00:00",
        "effective_to": "2026-02-01T00:00:00+00:00",
    })
    assert first.status_code == 201
    assert first.json()["organization_id"] == org.id
    assert first.json()["provider"] == "test-provider"
    assert first.json()["model"] == "test-model"

    overlap = await client.post(url, headers=headers, json={
        "provider": "test-provider",
        "model": "test-model",
        "input_price_per_million": "3",
        "output_price_per_million": "7",
        "effective_from": "2026-01-15T00:00:00+00:00",
        "effective_to": None,
    })
    assert overlap.status_code == 409

    adjacent = await client.post(url, headers=headers, json={
        "provider": "test-provider",
        "model": "test-model",
        "input_price_per_million": "3",
        "output_price_per_million": "7",
        "effective_from": "2026-02-01T00:00:00+00:00",
        "effective_to": None,
    })
    assert adjacent.status_code == 201

    overlapping_update = await client.patch(
        f"{url}/{first.json()['id']}",
        headers=headers,
        json={"effective_to": "2026-03-01T00:00:00+00:00"},
    )
    assert overlapping_update.status_code == 409

    own_update = await client.patch(
        f"{url}/{adjacent.json()['id']}",
        headers=headers,
        json={"input_price_per_million": "4"},
    )
    assert own_update.status_code == 200
    assert own_update.json()["input_price_per_million"] == 4
