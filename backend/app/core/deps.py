"""
Reusable FastAPI dependencies for authentication and role-based access control.

Usage:
    # Just require a valid JWT:
    user: User = Depends(current_user)

    # Require membership in the org from the URL path:
    ctx: OrgContext = Depends(require_org_member)

    # Require a specific minimum role:
    ctx: OrgContext = Depends(require_role(MemberRole.ADMIN))

    # Require owner:
    ctx: OrgContext = Depends(require_owner)
"""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt import decode_token
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.enums import MemberRole
from app.models.organization import OrganizationMember, User
from app.repositories import organization as org_repo
from app.repositories import user as user_repo
from app.services import audit as audit_svc
from app.models.enums import Severity

log = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Role hierarchy — higher index means more privilege
_ROLE_RANK: dict[MemberRole, int] = {
    MemberRole.VIEWER: 0,
    MemberRole.ANALYST: 1,
    MemberRole.DEVELOPER: 2,
    MemberRole.ADMIN: 3,
    MemberRole.OWNER: 4,
}


@dataclass
class OrgContext:
    user: User
    org_id: int
    member: OrganizationMember

    @property
    def role(self) -> MemberRole:
        return self.member.role

    @property
    def user_id(self) -> int:
        return self.user.id


# ── Token extraction ──────────────────────────────────────────────────────────

async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        user_id = decode_token(credentials.credentials, expected_type="access")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = await user_repo.get_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


# ── Org membership guard ──────────────────────────────────────────────────────

async def _resolve_org_context(
    org_id: int,
    user: User,
    db: AsyncSession,
    request: Request,
) -> OrgContext:
    """
    Verifies that `user` is a member of `org_id`.
    Logs and raises 403 on cross-org access attempts.
    """
    member = await org_repo.get_member(db, org_id=org_id, user_id=user.id)
    if member is None:
        log.warning(
            "rbac.cross_org_attempt",
            user_id=user.id,
            org_id=org_id,
            path=request.url.path,
        )
        await audit_svc.write(
            db,
            organization_id=org_id,
            user_id=user.id,
            event_type="auth.cross_org_access",
            entity_type="organization",
            entity_id=str(org_id),
            severity=Severity.HIGH,
            message=f"User {user.email} attempted to access org {org_id} without membership",
            ip_address=request.client.host if request.client else None,
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return OrgContext(user=user, org_id=org_id, member=member)


def _org_id_from_path(request: Request) -> int:
    raw = request.path_params.get("org_id")
    if raw is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing org_id in path")
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid org_id")


async def require_org_member(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> OrgContext:
    org_id = _org_id_from_path(request)
    return await _resolve_org_context(org_id, user, db, request)


# ── Role guards ───────────────────────────────────────────────────────────────

def require_role(minimum_role: MemberRole):
    """
    Factory that returns a dependency requiring at least `minimum_role`.

    Example:
        ctx: OrgContext = Depends(require_role(MemberRole.ADMIN))
    """
    async def _guard(
        request: Request,
        user: User = Depends(current_user),
        db: AsyncSession = Depends(get_db),
    ) -> OrgContext:
        org_id = _org_id_from_path(request)
        ctx = await _resolve_org_context(org_id, user, db, request)

        if _ROLE_RANK[ctx.role] < _ROLE_RANK[minimum_role]:
            log.warning(
                "rbac.insufficient_role",
                user_id=user.id,
                org_id=org_id,
                role=ctx.role,
                required=minimum_role,
                path=request.url.path,
            )
            await audit_svc.write(
                db,
                organization_id=org_id,
                user_id=user.id,
                event_type="auth.access_denied",
                severity=Severity.MEDIUM,
                message=(
                    f"User {user.email} (role={ctx.role}) attempted action "
                    f"requiring {minimum_role} on org {org_id}"
                ),
                ip_address=request.client.host if request.client else None,
            )
            await db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        return ctx

    return _guard


# Convenience shortcuts
require_viewer = require_role(MemberRole.VIEWER)
require_analyst = require_role(MemberRole.ANALYST)
require_developer = require_role(MemberRole.DEVELOPER)
require_admin = require_role(MemberRole.ADMIN)
require_owner = require_role(MemberRole.OWNER)
