"""
Tests for RBAC and organization isolation.

Verifies that:
- Each role can only perform permitted actions
- No cross-org data access is possible
- Removed members lose access
- Viewers cannot write
- Developers cannot administrate
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt import create_access_token
from app.models.enums import MemberRole
from app.tests.factories import make_member, make_org, make_user, make_user_with_org


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# ── Org access ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_member_can_get_org(client: AsyncClient, db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="viewer1@x.com", role=MemberRole.VIEWER, org_slug="v-org1")
    await db.commit()

    resp = await client.get(f"/api/v1/organizations/{org.id}", headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["slug"] == "v-org1"


@pytest.mark.asyncio
async def test_non_member_cannot_get_org(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner2@x.com", org_slug="o-org2")
    outsider = await make_user(db, email="outsider2@x.com")
    await db.commit()

    resp = await client.get(f"/api/v1/organizations/{org.id}", headers=_auth(outsider.id))
    assert resp.status_code == 403


# ── Org isolation — cross-org attempt ────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_org_access_denied(client: AsyncClient, db: AsyncSession):
    """User in org A cannot access org B endpoints."""
    _, org_a, _ = await make_user_with_org(db, email="usera@x.com", org_slug="cross-org-a")
    user_b, org_b, _ = await make_user_with_org(db, email="userb@x.com", org_slug="cross-org-b")
    # user_b tries to access org_a
    resp = await client.get(f"/api/v1/organizations/{org_a.id}", headers=_auth(user_b.id))
    assert resp.status_code == 403
    # user_a tries to access org_b
    user_a = (await db.execute(
        __import__("sqlalchemy", fromlist=["select"]).select(
            __import__("app.models.organization", fromlist=["User"]).User
        ).where(__import__("app.models.organization", fromlist=["User"]).User.email == "usera@x.com")
    )).scalar_one()
    resp = await client.get(f"/api/v1/organizations/{org_b.id}", headers=_auth(user_a.id))
    assert resp.status_code == 403


# ── Viewer — read-only ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_update_org(client: AsyncClient, db: AsyncSession):
    owner, org, _ = await make_user_with_org(db, email="owner3@x.com", org_slug="v-org3")
    viewer = await make_user(db, email="viewer3@x.com")
    await make_member(db, org, viewer, MemberRole.VIEWER)
    await db.commit()

    resp = await client.patch(
        f"/api/v1/organizations/{org.id}",
        json={"name": "Hacked"},
        headers=_auth(viewer.id),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_invite_members(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner4@x.com", org_slug="v-org4")
    viewer = await make_user(db, email="viewer4@x.com")
    await make_member(db, org, viewer, MemberRole.VIEWER)
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"email": "new@x.com", "role": "VIEWER"},
        headers=_auth(viewer.id),
    )
    assert resp.status_code == 403


# ── Developer — no admin actions ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_developer_cannot_remove_members(client: AsyncClient, db: AsyncSession):
    owner, org, owner_member = await make_user_with_org(db, email="owner5@x.com", org_slug="d-org5")
    dev = await make_user(db, email="dev5@x.com")
    await make_member(db, org, dev, MemberRole.DEVELOPER)
    await db.commit()

    resp = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{owner_member.id}",
        headers=_auth(dev.id),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_developer_cannot_update_org(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner6@x.com", org_slug="d-org6")
    dev = await make_user(db, email="dev6@x.com")
    await make_member(db, org, dev, MemberRole.DEVELOPER)
    await db.commit()

    resp = await client.patch(
        f"/api/v1/organizations/{org.id}",
        json={"name": "Changed"},
        headers=_auth(dev.id),
    )
    assert resp.status_code == 403


# ── Removed member loses access ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_removed_member_loses_access(client: AsyncClient, db: AsyncSession):
    owner, org, _ = await make_user_with_org(db, email="owner7@x.com", org_slug="rm-org7")
    victim = await make_user(db, email="victim7@x.com")
    victim_member = await make_member(db, org, victim, MemberRole.ANALYST)
    await db.commit()

    # Victim can access before removal
    resp = await client.get(f"/api/v1/organizations/{org.id}", headers=_auth(victim.id))
    assert resp.status_code == 200

    # Owner removes victim
    resp = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{victim_member.id}",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 204

    # Victim can no longer access
    resp = await client.get(f"/api/v1/organizations/{org.id}", headers=_auth(victim.id))
    assert resp.status_code == 403


# ── Admin cannot assign OWNER role ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_cannot_promote_to_owner(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner8@x.com", org_slug="adm-org8")
    admin = await make_user(db, email="admin8@x.com")
    target = await make_user(db, email="target8@x.com")
    admin_member = await make_member(db, org, admin, MemberRole.ADMIN)
    target_member = await make_member(db, org, target, MemberRole.VIEWER)
    await db.commit()

    resp = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{target_member.id}",
        json={"role": "OWNER"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 403


# ── Last owner protection ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cannot_remove_last_owner(client: AsyncClient, db: AsyncSession):
    owner, org, owner_member = await make_user_with_org(db, email="owner9@x.com", org_slug="lo-org9")
    await db.commit()

    resp = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{owner_member.id}",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 409


# ── Admin can invite members ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_can_invite_developer(client: AsyncClient, db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="owner10@x.com", org_slug="adm-org10")
    admin = await make_user(db, email="admin10@x.com")
    await make_member(db, org, admin, MemberRole.ADMIN)
    new_dev = await make_user(db, email="newdev10@x.com")
    await db.commit()

    resp = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"email": "newdev10@x.com", "role": "DEVELOPER"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "DEVELOPER"
