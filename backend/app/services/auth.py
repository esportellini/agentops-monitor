"""
Auth service: login, token refresh, logout.

Refresh tokens are stored in Redis so we can revoke individual sessions.
Key schema: auth:refresh:{jti} → user_id, TTL = refresh token lifetime.
Logout just deletes the Redis key.
"""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.jwt import create_access_token, create_refresh_token, decode_token
from app.core.logging import get_logger
from app.core.security import verify_password
from app.db.redis import get_redis
from app.models.enums import Severity
from app.models.organization import User
from app.repositories import user as user_repo
from app.services import audit as audit_svc

log = get_logger(__name__)

_REFRESH_PREFIX = "auth:refresh:"
_REFRESH_TTL = settings.jwt_refresh_expires_days * 86_400  # seconds


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    ip_address: str | None,
) -> tuple[str, str]:
    """
    Authenticate user. Returns (access_token, refresh_token).
    Raises AuthError on failure.
    """
    user = await user_repo.get_by_email(db, email)

    # Always run a dummy verify to prevent timing attacks
    if user is None:
        verify_password(password, "$2b$12$dummy.hash.to.prevent.timing.attack.padding.ok")
        log.warning("auth.login_failed.unknown_email", email=email, ip=ip_address)
        raise AuthError("Invalid credentials")

    if user_repo.is_locked(user):
        log.warning("auth.login_failed.locked", user_id=user.id, ip=ip_address)
        # Still write audit even for locked accounts (pick first org membership if any)
        await _write_failure_audit(db, user, ip_address, "Account temporarily locked")
        raise AuthError("Account temporarily locked. Try again later.", status=429)

    if not user.is_active:
        raise AuthError("Account inactive")

    if not verify_password(password, user.password_hash):
        await user_repo.record_login_failure(
            db, user,
            max_attempts=settings.login_max_attempts,
            lockout_minutes=settings.login_lockout_minutes,
        )
        await _write_failure_audit(db, user, ip_address, "Invalid password")
        await db.commit()
        log.warning("auth.login_failed.bad_password", user_id=user.id, ip=ip_address)
        raise AuthError("Invalid credentials")

    await user_repo.record_login_success(db, user)

    # Issue tokens
    access = create_access_token(user.id)
    refresh_jti = secrets.token_hex(32)
    refresh = create_refresh_token(user.id)

    redis = await get_redis()
    await redis.setex(f"{_REFRESH_PREFIX}{refresh_jti}", _REFRESH_TTL, str(user.id))

    # Embed jti in the refresh token via a side-channel (Redis key maps jti → user_id)
    # We store user_id:jti so refresh can validate and rotate
    await redis.setex(f"{_REFRESH_PREFIX}{refresh_jti}", _REFRESH_TTL, f"{user.id}:{refresh_jti}")

    await _write_login_audit(db, user, ip_address)
    await db.commit()

    log.info("auth.login_success", user_id=user.id, ip=ip_address)
    # Return refresh_jti embedded in refresh token via a cookie — caller stores it
    return access, refresh, refresh_jti


async def refresh(db: AsyncSession, *, refresh_jti: str) -> str:
    """Validate refresh token and issue a new access token. Returns new access_token."""
    redis = await get_redis()
    val = await redis.get(f"{_REFRESH_PREFIX}{refresh_jti}")
    if val is None:
        raise AuthError("Invalid or expired refresh token")

    user_id_str, _ = val.split(":", 1)
    user_id = int(user_id_str)

    user = await user_repo.get_by_id(db, user_id)
    if user is None or not user.is_active:
        await redis.delete(f"{_REFRESH_PREFIX}{refresh_jti}")
        raise AuthError("Invalid session")

    return create_access_token(user_id)


async def logout(refresh_jti: str) -> None:
    """Revoke a refresh token by removing it from Redis."""
    redis = await get_redis()
    await redis.delete(f"{_REFRESH_PREFIX}{refresh_jti}")


# ── helpers ───────────────────────────────────────────────────────────────────

async def _write_login_audit(db: AsyncSession, user: User, ip: str | None) -> None:
    org_id = await _first_org_id(db, user)
    if org_id:
        await audit_svc.write(
            db,
            organization_id=org_id,
            user_id=user.id,
            event_type="auth.login",
            entity_type="user",
            entity_id=str(user.id),
            message=f"{user.email} logged in",
            severity=Severity.INFO,
            ip_address=ip,
        )


async def _write_failure_audit(db: AsyncSession, user: User, ip: str | None, reason: str) -> None:
    org_id = await _first_org_id(db, user)
    if org_id:
        await audit_svc.write(
            db,
            organization_id=org_id,
            user_id=user.id,
            event_type="auth.login_failed",
            entity_type="user",
            entity_id=str(user.id),
            message=f"Login failed for {user.email}: {reason}",
            severity=Severity.MEDIUM,
            ip_address=ip,
        )


async def _first_org_id(db: AsyncSession, user: User) -> int | None:
    from sqlalchemy import select
    from app.models.organization import OrganizationMember
    result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
        .limit(1)
    )
    return result.scalar_one_or_none()
