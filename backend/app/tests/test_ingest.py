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

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MemberRole, ModelCallStatus, SpanStatus, SpanType, ToolCallStatus
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
    _, project, key = await _setup(db, "tagg")
    headers = _apikey_header(key)

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

    finish_resp = await client.post("/ingest/traces/trace-agg-001/finish", json={
        "status": "SUCCESS",
        "ended_at": _now(),
    }, headers=headers)

    data = finish_resp.json()
    assert data["total_input_tokens"] == 800
    assert data["total_output_tokens"] == 300
    assert abs(data["total_cost"] - 0.015) < 0.0001


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
