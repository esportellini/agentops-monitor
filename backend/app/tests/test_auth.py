"""
Tests for authentication flows.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt import create_access_token
from app.models.enums import MemberRole
from app.tests.factories import make_member, make_org, make_user, make_user_with_org


# ── Login ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, db: AsyncSession):
    await make_user_with_org(db, email="alice@x.com")
    await db.commit()

    resp = await client.post("/api/v1/auth/login", json={"email": "alice@x.com", "password": "password123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, db: AsyncSession):
    await make_user_with_org(db, email="bob@x.com")
    await db.commit()

    resp = await client.post("/api/v1/auth/login", json={"email": "bob@x.com", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient, db: AsyncSession):
    resp = await client.post("/api/v1/auth/login", json={"email": "nobody@x.com", "password": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, db: AsyncSession):
    user = await make_user(db, email="inactive@x.com", is_active=False)
    org = await make_org(db, slug="inactive-org")
    await make_member(db, org, user, MemberRole.OWNER)
    await db.commit()

    resp = await client.post("/api/v1/auth/login", json={"email": "inactive@x.com", "password": "password123"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_brute_force_lockout(client: AsyncClient, db: AsyncSession):
    await make_user_with_org(db, email="locked@x.com", org_slug="locked-org")
    await db.commit()

    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": "locked@x.com", "password": "bad"})

    # 6th attempt should be 429
    resp = await client.post("/api/v1/auth/login", json={"email": "locked@x.com", "password": "bad"})
    assert resp.status_code == 429


# ── /me ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient, db: AsyncSession):
    user, _, _ = await make_user_with_org(db, email="carol@x.com", org_slug="carol-org")
    await db.commit()

    token = create_access_token(user.id)
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "carol@x.com"


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
