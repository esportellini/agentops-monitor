"""
Tests for the ingest API.

Coverage:
- Create trace (start + finish)
- Add spans with hierarchy (parent/child)
- Finish trace aggregates tokens and cost
- Retry idempotency (same external_trace_id → same trace returned)
- Invalid API key returns 401
- API key scoped to project A cannot ingest into project B
- Batch: partial success when some items fail
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ingest as ingest_api
from app.models.enums import MemberRole, ModelCallStatus, SpanStatus, SpanType, ToolCallStatus
from app.models.organization import Organization
from app.models.pricing import ModelPricing
from app.models.trace import CostRecord, ModelCall, Trace
from app.tests.factories import (
    make_agent,
    make_api_key,
    make_environment,
    make_member,
    make_org,
    make_project,
    make_user,
    make_user_with_org,
)
from app.services.metrics import get_cost_summary


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apikey_header(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _setup(db: AsyncSession, org_slug: str = "ingest-org"):
    user, org, _ = await make_user_with_org(db, email=f"owner-{org_slug}@x.com", org_slug=org_slug)
    project = await make_project(db, org, slug=f"{org_slug}-proj")
    _, full_key = await make_api_key(db, org, name="test key")
    await db.commit()
    return org, project, full_key


async def _setup_project_scoped(db: AsyncSession, org_slug: str):
    user, org, _ = await make_user_with_org(db, email=f"owner-ps-{org_slug}@x.com", org_slug=org_slug)
    project = await make_project(db, org, slug=f"{org_slug}-proj")
    _, full_key = await make_api_key(db, org, project=project, name="project-scoped key")
    await db.commit()
    return org, project, full_key


async def _add_pricing(
    db: AsyncSession,
    org: Organization,
    *,
    provider: str,
    model: str,
    input_price: str,
    output_price: str,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> ModelPricing:
    pricing = ModelPricing(
        organization_id=org.id,
        provider=provider,
        model=model,
        input_price_per_million=Decimal(input_price),
        output_price_per_million=Decimal(output_price),
        effective_from=effective_from or datetime(2024, 1, 1, tzinfo=timezone.utc),
        effective_to=effective_to,
        active=True,
    )
    db.add(pricing)
    await db.flush()
    return pricing


# ── Trace create ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trace_start(client: AsyncClient, db: AsyncSession):
    org, project, key = await _setup(db, "tstart")

    resp = await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-001",
        "name": "test trace",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=_apikey_header(key))

    assert resp.status_code == 201
    data = resp.json()
    assert data["external_trace_id"] == "trace-001"
    assert data["status"] == "RUNNING"
    assert data["organization_id"] == org.id


@pytest.mark.asyncio
async def test_trace_start_and_finish(client: AsyncClient, db: AsyncSession):
    org, project, key = await _setup(db, "tfinish")

    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-fin-001",
        "name": "full trace",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=_apikey_header(key))

    resp = await client.post("/ingest/traces/trace-fin-001/finish", json={
        "status": "SUCCESS",
        "ended_at": _now(),
    }, headers=_apikey_header(key))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["duration_ms"] is not None


# ── Spans and hierarchy ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_span_create(client: AsyncClient, db: AsyncSession):
    _, project, key = await _setup(db, "tspan")

    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-span-001",
        "name": "span test",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=_apikey_header(key))

    resp = await client.post("/ingest/traces/trace-span-001/spans", json={
        "external_span_id": "span-001",
        "name": "root span",
        "type": "AGENT",
        "started_at": _now(),
    }, headers=_apikey_header(key))

    assert resp.status_code == 201
    assert resp.json()["external_span_id"] == "span-001"


@pytest.mark.asyncio
async def test_span_hierarchy(client: AsyncClient, db: AsyncSession):
    """Child span's parent_span_id resolves to the parent span's DB id."""
    _, project, key = await _setup(db, "thier")

    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-hier-001",
        "name": "hierarchy test",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=_apikey_header(key))

    parent_resp = await client.post("/ingest/traces/trace-hier-001/spans", json={
        "external_span_id": "parent-span",
        "name": "parent",
        "type": "AGENT",
        "started_at": _now(),
    }, headers=_apikey_header(key))
    parent_id = parent_resp.json()["id"]

    child_resp = await client.post("/ingest/traces/trace-hier-001/spans", json={
        "external_span_id": "child-span",
        "parent_span_id": "parent-span",
        "name": "child",
        "type": "LLM",
        "started_at": _now(),
    }, headers=_apikey_header(key))

    assert child_resp.status_code == 201
    assert child_resp.json()["parent_span_id"] == parent_id


# ── Token and cost aggregation ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_and_cost_aggregation(client: AsyncClient, db: AsyncSession):
    org, project, key = await _setup(db, "tagg")
    headers = _apikey_header(key)
    await _add_pricing(
        db,
        org,
        provider="openai",
        model="gpt-4o",
        input_price="0",
        output_price="50",
    )
    await db.commit()

    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-agg-001",
        "name": "agg test",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=headers)

    await client.post("/ingest/traces/trace-agg-001/spans", json={
        "external_span_id": "span-agg-001",
        "name": "llm span",
        "type": "LLM",
        "started_at": _now(),
    }, headers=headers)

    # Two model calls
    await client.post("/ingest/spans/span-agg-001/model-calls", json={
        "provider": "openai", "model": "gpt-4o",
        "input_tokens": 500, "output_tokens": 200, "estimated_cost": 0.01,
        "status": "SUCCESS",
    }, headers=headers)
    await client.post("/ingest/spans/span-agg-001/model-calls", json={
        "provider": "openai", "model": "gpt-4o",
        "input_tokens": 300, "output_tokens": 100, "estimated_cost": 0.005,
        "status": "SUCCESS",
    }, headers=headers)
    await client.post("/ingest/spans/span-agg-001/model-calls", json={
        "provider": "unknown-provider", "model": "unknown-model",
        "input_tokens": 50, "output_tokens": 25, "estimated_cost": 999,
        "status": "SUCCESS",
    }, headers=headers)

    finish_resp = await client.post("/ingest/traces/trace-agg-001/finish", json={
        "status": "SUCCESS",
        "ended_at": _now(),
    }, headers=headers)

    data = finish_resp.json()
    assert data["total_input_tokens"] == 850
    assert data["total_output_tokens"] == 325
    assert abs(data["total_cost"] - 0.015) < 0.0001
    assert data["unpriced_model_calls"] == 1


@pytest.mark.asyncio
async def test_model_call_cost_is_authoritative_and_snapshots_provenance(
    client: AsyncClient, db: AsyncSession
):
    org, project, key = await _setup(db, "tauthoritative")
    pricing = await _add_pricing(
        db,
        org,
        provider="test-provider",
        model="test-model",
        input_price="2",
        output_price="6",
    )
    await db.commit()
    headers = _apikey_header(key)

    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-authoritative",
        "name": "authoritative pricing",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=headers)
    await client.post("/ingest/traces/trace-authoritative/spans", json={
        "external_span_id": "span-authoritative",
        "name": "llm",
        "type": "LLM",
        "started_at": _now(),
    }, headers=headers)

    response = await client.post("/ingest/spans/span-authoritative/model-calls", json={
        "provider": " TEST-PROVIDER ",
        "model": " test-model ",
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
        "estimated_cost": 999999,
        "status": "SUCCESS",
    }, headers=headers)

    assert response.status_code == 201
    assert response.json()["estimated_cost"] == 5.0
    assert response.json()["pricing_status"] == "PRICED"
    zero_claim = await client.post("/ingest/spans/span-authoritative/model-calls", json={
        "provider": "test-provider",
        "model": "test-model",
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
        "estimated_cost": 0,
        "status": "SUCCESS",
    }, headers=headers)
    assert zero_claim.json()["estimated_cost"] == 5.0
    assert zero_claim.json()["pricing_status"] == "PRICED"
    model_call = await db.scalar(select(ModelCall).where(ModelCall.id == response.json()["id"]))
    cost_record = await db.scalar(
        select(CostRecord).where(CostRecord.model_call_id == model_call.id)
    )
    assert model_call.provider == "test-provider"
    assert Decimal(model_call.estimated_cost) == Decimal("5.00000000")
    assert cost_record.pricing_id == pricing.id
    assert Decimal(cost_record.cost_usd) == Decimal("5.00000000")
    assert Decimal(cost_record.input_price_per_million) == Decimal("2.00000000")
    assert Decimal(cost_record.output_price_per_million) == Decimal("6.00000000")

    pricing.input_price_per_million = Decimal("200")
    await db.flush()
    await db.refresh(cost_record)
    assert Decimal(cost_record.cost_usd) == Decimal("5.00000000")
    assert Decimal(cost_record.input_price_per_million) == Decimal("2.00000000")


@pytest.mark.asyncio
async def test_unknown_and_configured_free_calls_remain_distinct(
    client: AsyncClient, db: AsyncSession
):
    org, project, key = await _setup(db, "tunpriced")
    await _add_pricing(
        db,
        org,
        provider="free-provider",
        model="free-model",
        input_price="0",
        output_price="0",
    )
    await db.commit()
    headers = _apikey_header(key)
    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-unpriced",
        "name": "unpriced distinction",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=headers)
    await client.post("/ingest/traces/trace-unpriced/spans", json={
        "external_span_id": "span-unpriced",
        "name": "llm",
        "type": "LLM",
        "started_at": _now(),
    }, headers=headers)

    free = await client.post("/ingest/spans/span-unpriced/model-calls", json={
        "provider": "free-provider", "model": "free-model",
        "input_tokens": 100, "output_tokens": 50, "estimated_cost": 123,
        "status": "SUCCESS",
    }, headers=headers)
    unknown = await client.post("/ingest/spans/span-unpriced/model-calls", json={
        "provider": "unknown-provider", "model": "unknown-model",
        "input_tokens": 200, "output_tokens": 75, "estimated_cost": 456,
        "status": "SUCCESS",
    }, headers=headers)

    assert free.json()["pricing_status"] == "PRICED"
    assert free.json()["estimated_cost"] == 0
    assert unknown.json()["pricing_status"] == "UNPRICED"
    assert unknown.json()["estimated_cost"] == 0
    records = list((await db.scalars(
        select(CostRecord).where(CostRecord.organization_id == org.id)
    )).all())
    assert sorted(record.pricing_status for record in records) == ["PRICED", "UNPRICED"]

    finish = await client.post("/ingest/traces/trace-unpriced/finish", json={
        "status": "SUCCESS", "ended_at": _now(),
    }, headers=headers)
    assert finish.json()["total_input_tokens"] == 300
    assert finish.json()["total_output_tokens"] == 125
    assert finish.json()["total_cost"] == 0
    assert finish.json()["unpriced_model_calls"] == 1

    now = datetime.now(timezone.utc)
    summary = await get_cost_summary(
        db,
        org.id,
        since=now - timedelta(days=1),
        until=now + timedelta(days=1),
    )
    assert summary["unpriced_model_calls"] == 1
    rows = {row["model"]: row for row in summary["cost_by_model"]}
    assert rows["unknown-model"]["unpriced_calls"] == 1
    assert rows["free-model"]["unpriced_calls"] == 0


@pytest.mark.asyncio
async def test_model_call_uses_historical_price_at_exact_boundary(
    client: AsyncClient, db: AsyncSession
):
    org, project, key = await _setup(db, "thistorical")
    boundary = datetime(2026, 2, 1, tzinfo=timezone.utc)
    old = await _add_pricing(
        db,
        org,
        provider="history-provider",
        model="history-model",
        input_price="1",
        output_price="0",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_to=boundary,
    )
    new = await _add_pricing(
        db,
        org,
        provider="history-provider",
        model="history-model",
        input_price="2",
        output_price="0",
        effective_from=boundary,
    )
    await db.commit()
    headers = _apikey_header(key)
    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-history",
        "name": "historical pricing",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=headers)
    await client.post("/ingest/traces/trace-history/spans", json={
        "external_span_id": "span-history",
        "name": "llm",
        "type": "LLM",
        "started_at": _now(),
    }, headers=headers)

    before = await client.post("/ingest/spans/span-history/model-calls", json={
        "provider": "history-provider", "model": "history-model",
        "input_tokens": 1_000_000, "output_tokens": 0,
        "occurred_at": "2026-01-31T23:59:59.999999+00:00",
        "status": "SUCCESS",
    }, headers=headers)
    at_boundary = await client.post("/ingest/spans/span-history/model-calls", json={
        "provider": "history-provider", "model": "history-model",
        "input_tokens": 1_000_000, "output_tokens": 0,
        "occurred_at": boundary.isoformat(),
        "status": "SUCCESS",
    }, headers=headers)

    assert before.json()["estimated_cost"] == 1
    assert before.json()["pricing_id"] == old.id
    assert at_boundary.json()["estimated_cost"] == 2
    assert at_boundary.json()["pricing_id"] == new.id


@pytest.mark.asyncio
async def test_batch_model_call_uses_authoritative_pricing_pipeline(
    client: AsyncClient, db: AsyncSession
):
    org, project, key = await _setup(db, "tbatch-pricing")
    pricing = await _add_pricing(
        db,
        org,
        provider="batch-provider",
        model="batch-model",
        input_price="2",
        output_price="6",
    )
    await db.commit()
    headers = _apikey_header(key)
    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-batch-pricing",
        "name": "batch pricing",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=headers)
    await client.post("/ingest/traces/trace-batch-pricing/spans", json={
        "external_span_id": "span-batch-pricing",
        "name": "llm",
        "type": "LLM",
        "started_at": _now(),
    }, headers=headers)

    response = await client.post("/ingest/batch", json={"items": [{
        "type": "model_call",
        "external_span_id": "span-batch-pricing",
        "payload": {
            "provider": "batch-provider", "model": "batch-model",
            "input_tokens": 1_000_000, "output_tokens": 500_000,
            "estimated_cost": 999999, "status": "SUCCESS",
        },
    }]}, headers=headers)

    assert response.json()["accepted"] == 1
    call = await db.scalar(select(ModelCall).where(ModelCall.provider == "batch-provider"))
    record = await db.scalar(select(CostRecord).where(CostRecord.model_call_id == call.id))
    assert Decimal(call.estimated_cost) == Decimal("5.00000000")
    assert record.pricing_id == pricing.id


# ── Idempotency ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trace_start_idempotent(client: AsyncClient, db: AsyncSession):
    """Starting the same trace twice returns the same trace (no duplicate)."""
    _, project, key = await _setup(db, "tidm")
    headers = _apikey_header(key)

    body = {
        "external_trace_id": "trace-idem-001",
        "name": "idempotent trace",
        "project_id": project.id,
        "started_at": _now(),
    }
    r1 = await client.post("/ingest/traces/start", json=body, headers=headers)
    r2 = await client.post("/ingest/traces/start", json=body, headers=headers)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_span_create_idempotent(client: AsyncClient, db: AsyncSession):
    _, project, key = await _setup(db, "tisp")
    headers = _apikey_header(key)

    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-isp-001",
        "name": "span idem",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=headers)

    body = {"external_span_id": "span-isp", "name": "root", "type": "AGENT", "started_at": _now()}
    r1 = await client.post("/ingest/traces/trace-isp-001/spans", json=body, headers=headers)
    r2 = await client.post("/ingest/traces/trace-isp-001/spans", json=body, headers=headers)

    assert r1.json()["id"] == r2.json()["id"]


# ── Auth failures ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_api_key_rejected(client: AsyncClient, db: AsyncSession):
    resp = await client.post("/ingest/traces/start", json={
        "external_trace_id": "x",
        "name": "x",
        "project_id": 1,
        "started_at": _now(),
    }, headers=_apikey_header("agom_notavalidkey000000000000000000000000000000000000000000000000000"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_api_key_rejected(client: AsyncClient, db: AsyncSession):
    resp = await client.post("/ingest/traces/start", json={
        "external_trace_id": "x", "name": "x", "project_id": 1, "started_at": _now(),
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_project_scoped_key_cannot_ingest_other_project(client: AsyncClient, db: AsyncSession):
    """Key scoped to project A must not ingest data for project B."""
    org, project_a, key_a = await _setup_project_scoped(db, "tscope")
    project_b = await make_project(db, org, slug="tscope-proj-b")
    await db.commit()

    resp = await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-scope-001",
        "name": "cross project",
        "project_id": project_b.id,  # different project
        "started_at": _now(),
    }, headers=_apikey_header(key_a))

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_org_scoped_key_cannot_ingest_project_from_other_org(
    client: AsyncClient, db: AsyncSession
):
    """An organization key must only write to projects owned by that organization."""
    _, _, key_a = await _setup(db, "torgscope-a")
    _, project_b, _ = await _setup(db, "torgscope-b")

    resp = await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-cross-org-001",
        "name": "cross organization",
        "project_id": project_b.id,
        "started_at": _now(),
    }, headers=_apikey_header(key_a))

    assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["agent_id", "environment_id"])
async def test_trace_rejects_reference_from_other_organization(
    reference: str, client: AsyncClient, db: AsyncSession
):
    _, project_a, key_a = await _setup(db, f"xref-org-a-{reference}")
    _, project_b, _ = await _setup(db, f"xref-org-b-{reference}")
    foreign = (
        await make_agent(db, project_b, slug=f"foreign-{reference}")
        if reference == "agent_id"
        else await make_environment(db, project_b, name=f"foreign-{reference}")
    )
    await db.commit()

    resp = await client.post("/ingest/traces/start", json={
        "external_trace_id": f"trace-xref-org-{reference}",
        "name": "cross organization reference",
        "project_id": project_a.id,
        reference: foreign.id,
        "started_at": _now(),
    }, headers=_apikey_header(key_a))

    assert resp.status_code == 403
    assert resp.json()["detail"] == "API key is not authorized for this resource"


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["agent_id", "environment_id"])
async def test_trace_rejects_reference_from_other_project_in_same_organization(
    reference: str, client: AsyncClient, db: AsyncSession
):
    org, project_a, key = await _setup(db, f"xref-project-{reference}")
    project_b = await make_project(db, org, slug=f"second-{reference}")
    foreign = (
        await make_agent(db, project_b, slug=f"other-{reference}")
        if reference == "agent_id"
        else await make_environment(db, project_b, name=f"other-{reference}")
    )
    await db.commit()

    resp = await client.post("/ingest/traces/start", json={
        "external_trace_id": f"trace-xref-project-{reference}",
        "name": "cross project reference",
        "project_id": project_a.id,
        reference: foreign.id,
        "started_at": _now(),
    }, headers=_apikey_header(key))

    assert resp.status_code == 403
    assert resp.json()["detail"] == "API key is not authorized for this resource"


# ── Tool calls ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_call_ingest(client: AsyncClient, db: AsyncSession):
    _, project, key = await _setup(db, "ttool")
    headers = _apikey_header(key)

    await client.post("/ingest/traces/start", json={
        "external_trace_id": "trace-tool-001",
        "name": "tool test",
        "project_id": project.id,
        "started_at": _now(),
    }, headers=headers)
    await client.post("/ingest/traces/trace-tool-001/spans", json={
        "external_span_id": "span-tool-001",
        "name": "tool span",
        "type": "TOOL",
        "started_at": _now(),
    }, headers=headers)

    resp = await client.post("/ingest/spans/span-tool-001/tool-calls", json={
        "tool_name": "search_db",
        "input_data": {"query": "SELECT * FROM users"},
        "status": "SUCCESS",
        "duration_ms": 45,
    }, headers=headers)

    assert resp.status_code == 201
    assert resp.json()["tool_name"] == "search_db"


# ── Batch ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_ingest_success(client: AsyncClient, db: AsyncSession):
    _, project, key = await _setup(db, "tbatch")

    resp = await client.post("/ingest/batch", json={"items": [
        {
            "type": "trace_start",
            "external_trace_id": "trace-batch-001",
            "payload": {
                "external_trace_id": "trace-batch-001",
                "name": "batch trace",
                "project_id": project.id,
                "started_at": _now(),
            },
        },
        {
            "type": "span",
            "external_trace_id": "trace-batch-001",
            "payload": {
                "external_span_id": "span-batch-001",
                "name": "batch span",
                "type": "AGENT",
                "started_at": _now(),
            },
        },
        {
            "type": "trace_finish",
            "external_trace_id": "trace-batch-001",
            "payload": {"status": "SUCCESS", "ended_at": _now()},
        },
    ]}, headers=_apikey_header(key))

    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 3
    assert data["failed"] == 0


@pytest.mark.asyncio
async def test_batch_partial_failure(client: AsyncClient, db: AsyncSession):
    """Bad items fail; good items succeed. Partial result returned."""
    _, project, key = await _setup(db, "tbpart")

    resp = await client.post("/ingest/batch", json={"items": [
        {
            "type": "trace_start",
            "external_trace_id": "trace-partial-001",
            "payload": {
                "external_trace_id": "trace-partial-001",
                "name": "partial trace",
                "project_id": project.id,
                "started_at": _now(),
            },
        },
        {
            "type": "span",
            "external_trace_id": "trace-DOES-NOT-EXIST",  # bad trace id
            "payload": {
                "external_span_id": "span-bad-001",
                "name": "orphan span",
                "type": "LLM",
                "started_at": _now(),
            },
        },
    ]}, headers=_apikey_header(key))

    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1
    assert data["failed"] == 1
    assert data["results"][0]["ok"] is True
    assert data["results"][1]["ok"] is False


@pytest.mark.asyncio
async def test_batch_savepoint_recovers_from_real_integrity_error(
    client: AsyncClient, db: AsyncSession, monkeypatch
):
    """A database constraint failure in one item must not poison later items."""
    _, project, key = await _setup(db, "tbatch-savepoint")
    original_process = ingest_api._process_batch_item

    async def process_with_database_failure(db_session, ctx, item):
        if item.type == "event" and item.payload.get("event_type") == "force_db_error":
            db_session.add(Organization(name="Duplicate A", slug="forced-duplicate"))
            await db_session.flush()
            db_session.add(Organization(name="Duplicate B", slug="forced-duplicate"))
            await db_session.flush()
            return
        await original_process(db_session, ctx, item)

    monkeypatch.setattr(ingest_api, "_process_batch_item", process_with_database_failure)
    response = await client.post("/ingest/batch", json={"items": [
        {
            "type": "trace_start",
            "payload": {
                "external_trace_id": "trace-before-db-error",
                "name": "before",
                "project_id": project.id,
                "started_at": _now(),
            },
        },
        {
            "type": "event",
            "external_trace_id": "unused",
            "payload": {"event_type": "force_db_error", "message": "safe"},
        },
        {
            "type": "trace_start",
            "payload": {
                "external_trace_id": "trace-after-db-error",
                "name": "after",
                "project_id": project.id,
                "started_at": _now(),
            },
        },
    ]}, headers=_apikey_header(key))

    persisted = await db.scalar(select(func.count()).select_from(Trace))
    assert response.status_code == 200
    assert response.json()["accepted"] == 2
    assert response.json()["failed"] == 1
    assert persisted == 2
