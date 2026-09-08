from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt import create_access_token
from app.models.audit import AuditLog
from app.models.enums import MemberRole
from app.models.security import AgentPolicy, ToolApproval
from app.models.trace import ToolCall
from app.tests.factories import (
    make_agent, make_api_key, make_member, make_org, make_project, make_user,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def _jwt(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _setup(db: AsyncSession, slug: str = "approval"):
    owner = await make_user(db, email=f"{slug}-owner@example.com")
    org = await make_org(db, name=slug, slug=slug)
    await make_member(db, org, owner, MemberRole.OWNER)
    project = await make_project(db, org, slug=f"{slug}-project")
    agent = await make_agent(db, project, slug=f"{slug}-agent")
    policy = AgentPolicy(
        organization_id=org.id, agent_id=agent.id,
        tools_requiring_approval=["send_email"],
    )
    db.add(policy)
    _, project_key = await make_api_key(db, org, project=project)
    _, org_key = await make_api_key(db, org)
    await db.commit()
    return owner, org, project, agent, policy, project_key, org_key


async def _trace_and_span(client, project, agent, key, trace_id="approval-trace", span_id="approval-span"):
    await client.post("/ingest/traces/start", json={
        "external_trace_id": trace_id, "name": trace_id, "project_id": project.id,
        "agent_id": agent.id, "started_at": _now(),
    }, headers=_key(key))
    await client.post(f"/ingest/traces/{trace_id}/spans", json={
        "external_span_id": span_id, "name": span_id, "type": "TOOL",
        "started_at": _now(), "status": "SUCCESS",
    }, headers=_key(key))


async def _preflight(client, key, request_id, trace_id="approval-trace", **extra):
    payload = {
        "external_trace_id": trace_id,
        "tool_name": "send_email",
        "external_request_id": request_id,
        **extra,
    }
    return await client.post("/ingest/policy/check-tool", json=payload, headers=_key(key))


@pytest.mark.asyncio
async def test_require_approval_creates_reuses_and_sanitizes_request(
    client: AsyncClient, db: AsyncSession
):
    owner, org, project, agent, _, key, _ = await _setup(db, "approval-create")
    await _trace_and_span(client, project, agent, key)
    secret = "sk-abcdefghijklmnopqrstuvwxyzABCDEFGH"
    first = await _preflight(
        client, key, "attempt-1", external_span_id="approval-span",
        target_url="https://user:password@example.com/path?token=secret#fragment",
        approval_context={"recipient": "finance", "api_key": secret},
    )
    retry = await _preflight(
        client, key, "attempt-1", external_span_id="approval-span",
        target_url="https://user:password@example.com/path?token=other#ignored",
        approval_context={"recipient": "finance", "api_key": secret},
    )
    second = await _preflight(client, key, "attempt-2")
    assert first.status_code == retry.status_code == second.status_code == 200
    assert first.json()["decision"] == "REQUIRE_APPROVAL"
    assert first.json()["approval_id"] == retry.json()["approval_id"]
    assert second.json()["approval_id"] != first.json()["approval_id"]
    approvals = (await db.execute(select(ToolApproval).order_by(ToolApproval.id))).scalars().all()
    assert len(approvals) == 2
    assert approvals[0].target_url == "https://example.com/path"
    assert secret not in str(approvals[0].tool_input)
    assert approvals[0].span_id is not None
    audit = await db.scalar(select(AuditLog).where(AuditLog.event_type == "tool_approval.created"))
    assert audit is not None and secret not in str(audit.after_data)
    detail = await client.get(
        f"/api/v1/organizations/{org.id}/tool-approvals/{approvals[0].id}",
        headers=_jwt(owner.id),
    )
    assert detail.status_code == 200
    assert detail.json()["approval_context"]["api_key"] == "[BLOCKED_BY_POLICY]"
    assert secret not in detail.text
    assert secret not in first.text
    assert await db.scalar(select(ToolCall)) is None


@pytest.mark.asyncio
async def test_approve_revalidate_execute_consume_and_retry_telemetry(
    client: AsyncClient, db: AsyncSession
):
    owner, _, project, agent, _, key, _ = await _setup(db, "approval-execute")
    await _trace_and_span(client, project, agent, key)
    pending = (await _preflight(client, key, "execute-once")).json()
    approval_id = pending["approval_id"]
    approved = await client.post(
        f"/api/v1/organizations/{project.organization_id}/tool-approvals/{approval_id}/approve",
        json={"note": "Reviewed"}, headers=_jwt(owner.id),
    )
    assert approved.status_code == 200
    granted = await _preflight(client, key, "execute-once")
    assert granted.json()["decision"] == "ALLOW"
    assert granted.json()["reason_code"] == "APPROVAL_GRANTED"
    payload = {"tool_name": "send_email", "status": "SUCCESS", "approval_id": approval_id}
    first = await client.post(
        "/ingest/spans/approval-span/tool-calls", json=payload, headers=_key(key)
    )
    retry = await client.post(
        "/ingest/spans/approval-span/tool-calls", json=payload, headers=_key(key)
    )
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert await db.scalar(select(func.count()).select_from(ToolCall)) == 1
    approval = await db.get(ToolApproval, approval_id)
    assert approval.used_at is not None
    reused = await _preflight(client, key, "execute-once")
    assert reused.json()["reason_code"] == "APPROVAL_ALREADY_USED"
    events = (await db.execute(select(AuditLog.event_type))).scalars().all()
    assert "tool_approval.approved" in events
    assert "tool_approval.executed" in events


@pytest.mark.asyncio
async def test_reject_is_final_and_second_transition_conflicts(
    client: AsyncClient, db: AsyncSession
):
    owner, org, project, agent, _, key, _ = await _setup(db, "approval-reject")
    await _trace_and_span(client, project, agent, key)
    approval_id = (await _preflight(client, key, "reject-me")).json()["approval_id"]
    rejected = await client.post(
        f"/api/v1/organizations/{org.id}/tool-approvals/{approval_id}/reject",
        json={"note": "No"}, headers=_jwt(owner.id),
    )
    assert rejected.status_code == 200
    conflict = await client.post(
        f"/api/v1/organizations/{org.id}/tool-approvals/{approval_id}/approve",
        json={}, headers=_jwt(owner.id),
    )
    assert conflict.status_code == 409
    check = await _preflight(client, key, "reject-me")
    assert check.json()["decision"] == "BLOCK"
    assert check.json()["reason_code"] == "APPROVAL_REJECTED"


@pytest.mark.asyncio
async def test_approved_request_is_blocked_after_policy_or_budget_changes(
    client: AsyncClient, db: AsyncSession
):
    owner, org, project, agent, policy, key, _ = await _setup(db, "approval-stale")
    await _trace_and_span(client, project, agent, key)
    approval_id = (await _preflight(
        client, key, "stale-policy", target_url="https://api.example.com/path"
    )).json()["approval_id"]
    await client.post(
        f"/api/v1/organizations/{org.id}/tool-approvals/{approval_id}/approve",
        json={}, headers=_jwt(owner.id),
    )
    policy.blocked_tools = ["send_email"]
    await db.commit()
    blocked = await _preflight(
        client, key, "stale-policy", target_url="https://api.example.com/path"
    )
    assert blocked.json()["reason_code"] == "TOOL_BLOCKED"


@pytest.mark.asyncio
async def test_approved_request_revalidates_domain_and_trace_budget(
    client: AsyncClient, db: AsyncSession
):
    owner, org, project, agent, policy, key, _ = await _setup(db, "approval-revalidate")
    policy.allowed_domains = ["example.com"]
    policy.max_tokens_per_trace = 0
    await db.commit()
    await _trace_and_span(client, project, agent, key)

    domain_id = (await _preflight(
        client, key, "domain-change", target_url="https://api.example.com/path"
    )).json()["approval_id"]
    await client.post(
        f"/api/v1/organizations/{org.id}/tool-approvals/{domain_id}/approve",
        json={}, headers=_jwt(owner.id),
    )
    policy.blocked_domains = ["example.com"]
    await db.commit()
    domain_block = await _preflight(
        client, key, "domain-change", target_url="https://api.example.com/path"
    )
    assert domain_block.json()["reason_code"] == "DOMAIN_BLOCKED"

    policy.blocked_domains = []
    await db.commit()
    budget_id = (await _preflight(client, key, "budget-change")).json()["approval_id"]
    await client.post(
        f"/api/v1/organizations/{org.id}/tool-approvals/{budget_id}/approve",
        json={}, headers=_jwt(owner.id),
    )
    await client.post("/ingest/spans/approval-span/model-calls", json={
        "provider": "test", "model": "unpriced", "input_tokens": 1,
        "output_tokens": 0, "status": "SUCCESS",
    }, headers=_key(key))
    budget_block = await _preflight(client, key, "budget-change")
    assert budget_block.json()["reason_code"] == "TRACE_TOKEN_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_approval_scope_and_reviewer_rbac_are_enforced(
    client: AsyncClient, db: AsyncSession
):
    owner, org, project, agent, _, key, org_key = await _setup(db, "approval-scope")
    await _trace_and_span(client, project, agent, key)
    approval_id = (await _preflight(client, key, "scope-attempt")).json()["approval_id"]

    other_project = await make_project(db, org, name="Other", slug="approval-scope-other")
    _, other_key = await make_api_key(db, org, project=other_project)
    foreign_org = await make_org(db, name="Foreign", slug="approval-scope-foreign")
    _, foreign_key = await make_api_key(db, foreign_org)
    viewer = await make_user(db, email="approval-viewer@example.com")
    await make_member(db, org, viewer, MemberRole.VIEWER)
    await db.commit()
    path = f"/ingest/policy/approvals/{approval_id}"
    assert (await client.get(path, headers=_key(key))).status_code == 200
    assert (await client.get(path, headers=_key(other_key))).status_code == 404
    assert (await client.get(path, headers=_key(foreign_key))).status_code == 404
    denied = await client.post(
        f"/api/v1/organizations/{org.id}/tool-approvals/{approval_id}/approve",
        json={}, headers=_jwt(viewer.id),
    )
    assert denied.status_code == 403

    management_base = f"/api/v1/organizations/{org.id}/tool-approvals"
    listed = await client.get(
        f"{management_base}?status=pending&agent_id={agent.id}&tool=send_email",
        headers=_jwt(owner.id),
    )
    detail = await client.get(f"{management_base}/{approval_id}", headers=_jwt(owner.id))
    assert listed.status_code == detail.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [approval_id]
    assert detail.json()["external_request_id"] == "scope-attempt"

    foreign_owner = await make_user(db, email="approval-foreign-owner@example.com")
    await make_member(db, foreign_org, foreign_owner, MemberRole.OWNER)
    await db.commit()
    assert (await client.get(
        f"/api/v1/organizations/{foreign_org.id}/tool-approvals/{approval_id}",
        headers=_jwt(foreign_owner.id),
    )).status_code == 404
    assert (await client.post(
        f"/api/v1/organizations/{foreign_org.id}/tool-approvals/{approval_id}/approve",
        json={}, headers=_jwt(foreign_owner.id),
    )).status_code == 404

    await client.post(
        f"/api/v1/organizations/{org.id}/tool-approvals/{approval_id}/approve",
        json={}, headers=_jwt(owner.id),
    )
    await _trace_and_span(
        client, project, agent, org_key, trace_id="other-trace", span_id="other-span"
    )
    wrong_trace = await client.post("/ingest/spans/other-span/tool-calls", json={
        "tool_name": "send_email", "status": "SUCCESS", "approval_id": approval_id,
    }, headers=_key(org_key))
    wrong_tool = await client.post("/ingest/spans/approval-span/tool-calls", json={
        "tool_name": "other_tool", "status": "SUCCESS", "approval_id": approval_id,
    }, headers=_key(key))
    assert wrong_trace.status_code == wrong_tool.status_code == 403
