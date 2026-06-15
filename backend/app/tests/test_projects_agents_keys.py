"""
Tests: projects, agents, environments, API keys.

Coverage:
- Project creation and org isolation
- Agent creation, versioning, status changes
- API key generation, revocation, validation
- Role enforcement (viewer cannot create, developer can, admin can delete)
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt import create_access_token
from app.models.enums import AgentStatus, MemberRole
from app.services.api_key import generate_api_key, verify_api_key
from app.tests.factories import (
    make_agent,
    make_environment,
    make_member,
    make_org,
    make_project,
    make_user,
    make_user_with_org,
)


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# ── Projects ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_as_developer(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-p1@x.com", role=MemberRole.DEVELOPER, org_slug="proj-org1")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Alpha", "slug": "alpha"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "alpha"
    assert data["organization_id"] == org.id


@pytest.mark.asyncio
async def test_viewer_cannot_create_project(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner-p2@x.com", org_slug="proj-org2")
    viewer = await make_user(db, email="viewer-p2@x.com")
    await make_member(db, org, viewer, MemberRole.VIEWER)
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Forbidden", "slug": "forbidden"},
        headers=_auth(viewer.id),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_project_org_isolation(client: AsyncClient, db: AsyncSession):
    """User in org A cannot read projects from org B."""
    _, org_a, _ = await make_user_with_org(db, email="owner-pa@x.com", org_slug="iso-org-a")
    user_b, org_b, _ = await make_user_with_org(db, email="owner-pb@x.com", org_slug="iso-org-b")
    project_a = await make_project(db, org_a, slug="proj-a-iso")
    await db.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org_a.id}/projects/{project_a.id}",
        headers=_auth(user_b.id),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_slug_rejected(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="owner-dup@x.com", org_slug="dup-org")
    await make_project(db, org, slug="dup-slug")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Another", "slug": "dup-slug"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_project_requires_admin(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner-del@x.com", org_slug="del-org")
    dev = await make_user(db, email="dev-del@x.com")
    await make_member(db, org, dev, MemberRole.DEVELOPER)
    project = await make_project(db, org, slug="del-proj")
    await db.commit()

    resp = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}",
        headers=_auth(dev.id),
    )
    assert resp.status_code == 403


# ── Agents ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_agent(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-ag1@x.com", role=MemberRole.DEVELOPER, org_slug="ag-org1")
    project = await make_project(db, org, slug="ag-proj1")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/agents",
        json={
            "project_id": project.id,
            "name": "Support Bot",
            "slug": "support-bot",
            "version": "1.0.0",
            "model_provider": "openai",
            "default_model": "gpt-4o",
        },
        headers=_auth(user.id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "support-bot"
    assert data["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_agent_version_bump(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-av@x.com", role=MemberRole.DEVELOPER, org_slug="av-org")
    project = await make_project(db, org, slug="av-proj")
    agent = await make_agent(db, project, slug="version-bot", version="1.0.0")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/agents/{agent.id}/new-version",
        json={"version": "1.1.0"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.1.0"


@pytest.mark.asyncio
async def test_agent_auto_version_bump(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-aav@x.com", role=MemberRole.DEVELOPER, org_slug="aav-org")
    project = await make_project(db, org, slug="aav-proj")
    agent = await make_agent(db, project, slug="auto-version-bot", version="2.3.1")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/agents/{agent.id}/new-version",
        json={"version": ""},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == "2.3.2"


@pytest.mark.asyncio
async def test_agent_status_change(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-as@x.com", role=MemberRole.DEVELOPER, org_slug="as-org")
    project = await make_project(db, org, slug="as-proj")
    agent = await make_agent(db, project, slug="status-bot")
    await db.commit()

    resp = await client.patch(
        f"/api/v1/organizations/{org.id}/agents/{agent.id}/status",
        json={"status": "PAUSED"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PAUSED"


@pytest.mark.asyncio
async def test_agent_org_isolation(client: AsyncClient, db: AsyncSession):
    _, org_a, _ = await make_user_with_org(db, email="owner-aio-a@x.com", org_slug="aio-org-a")
    user_b, org_b, _ = await make_user_with_org(db, email="owner-aio-b@x.com", org_slug="aio-org-b")
    project_a = await make_project(db, org_a, slug="aio-proj-a")
    agent_a = await make_agent(db, project_a, slug="aio-agent-a")
    await db.commit()

    resp = await client.get(
        f"/api/v1/organizations/{org_a.id}/agents/{agent_a.id}",
        headers=_auth(user_b.id),
    )
    assert resp.status_code == 403


# ── API Keys ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_key_generation_format():
    """Key must start with agom_ prefix and hash must verify."""
    full_key, prefix, key_hash = generate_api_key()
    assert full_key.startswith("agom_")
    assert prefix.startswith("agom_")
    assert len(prefix) < len(full_key)
    assert verify_api_key(full_key, key_hash)


@pytest.mark.asyncio
async def test_wrong_key_does_not_verify():
    _, _, key_hash = generate_api_key()
    assert not verify_api_key("agom_wrongkey", key_hash)


@pytest.mark.asyncio
async def test_create_api_key_shows_full_key_once(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-key1@x.com", role=MemberRole.DEVELOPER, org_slug="key-org1")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys",
        json={"name": "CI key"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "key" in data
    assert data["key"].startswith("agom_")
    # Full key not returned on list
    list_resp = await client.get(
        f"/api/v1/organizations/{org.id}/api-keys",
        headers=_auth(user.id),
    )
    listed = list_resp.json()
    assert all("key" not in k for k in listed)


@pytest.mark.asyncio
async def test_viewer_cannot_create_api_key(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner-key2@x.com", org_slug="key-org2")
    viewer = await make_user(db, email="viewer-key2@x.com")
    await make_member(db, org, viewer, MemberRole.VIEWER)
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys",
        json={"name": "Bad key"},
        headers=_auth(viewer.id),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_revoke_api_key(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-rev@x.com", role=MemberRole.DEVELOPER, org_slug="rev-org")
    await db.commit()

    # Create key
    create_resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys",
        json={"name": "Temp key"},
        headers=_auth(user.id),
    )
    key_id = create_resp.json()["id"]

    # Revoke it
    revoke_resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys/{key_id}/revoke",
        headers=_auth(user.id),
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "REVOKED"


@pytest.mark.asyncio
async def test_revoke_already_revoked_fails(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-rrv@x.com", role=MemberRole.DEVELOPER, org_slug="rrv-org")
    await db.commit()

    create_resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys",
        json={"name": "Double revoke"},
        headers=_auth(user.id),
    )
    key_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/organizations/{org.id}/api-keys/{key_id}/revoke",
        headers=_auth(user.id),
    )
    resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys/{key_id}/revoke",
        headers=_auth(user.id),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_key_scoped_to_project(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="dev-scoped@x.com", role=MemberRole.DEVELOPER, org_slug="scoped-org")
    project = await make_project(db, org, slug="scoped-proj")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys",
        json={"name": "Project key", "project_id": project.id},
        headers=_auth(user.id),
    )
    assert resp.status_code == 201
    assert resp.json()["project_id"] == project.id


@pytest.mark.asyncio
async def test_api_key_cross_org_rejected(client: AsyncClient, db: AsyncSession):
    """Cannot create a key scoped to another org's project."""
    _, org_a, _ = await make_user_with_org(db, email="owner-ka@x.com", org_slug="key-org-a")
    user_b, org_b, _ = await make_user_with_org(db, email="owner-kb@x.com", org_slug="key-org-b")
    project_a = await make_project(db, org_a, slug="key-proj-a")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org_b.id}/api-keys",
        json={"name": "Cross-org key", "project_id": project_a.id},
        headers=_auth(user_b.id),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_api_key_requires_admin(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner-kdel@x.com", org_slug="kdel-org")
    dev = await make_user(db, email="dev-kdel@x.com")
    await make_member(db, org, dev, MemberRole.DEVELOPER)
    await db.commit()

    create_resp = await client.post(
        f"/api/v1/organizations/{org.id}/api-keys",
        json={"name": "Delete me"},
        headers=_auth(dev.id),
    )
    key_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/organizations/{org.id}/api-keys/{key_id}",
        headers=_auth(dev.id),
    )
    assert resp.status_code == 403
