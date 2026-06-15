from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.enums import Severity
from app.models.organization import User
from app.repositories.auth_helpers import first_org_id_for_user
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse
from app.services import audit as audit_svc
from app.services import auth as auth_svc

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)

_REFRESH_COOKIE = "refresh_token_id"


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host if request.client else None
    try:
        access, _refresh_jwt, refresh_jti = await auth_svc.login(
            db, email=payload.email, password=payload.password, ip_address=ip
        )
    except auth_svc.AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))

    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_jti,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=auth_svc._REFRESH_TTL,
        path="/api/v1/auth",
    )
    return TokenResponse(access_token=access)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    refresh_jti = request.cookies.get(_REFRESH_COOKIE)
    if not refresh_jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    try:
        access = await auth_svc.refresh(db, refresh_jti=refresh_jti)
    except auth_svc.AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))

    return TokenResponse(access_token=access)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    refresh_jti = request.cookies.get(_REFRESH_COOKIE)
    if refresh_jti:
        await auth_svc.logout(refresh_jti)

    response.delete_cookie(_REFRESH_COOKIE, path="/api/v1/auth")

    org_id = await first_org_id_for_user(db, user.id)
    if org_id:
        await audit_svc.write(
            db,
            organization_id=org_id,
            user_id=user.id,
            event_type="auth.logout",
            message=f"{user.email} logged out",
            severity=Severity.INFO,
            ip_address=request.client.host if request.client else None,
        )
        await db.commit()


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(current_user)):
    return MeResponse(id=user.id, email=user.email, name=user.name, is_active=user.is_active)
