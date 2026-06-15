from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_admin, require_developer, require_org_member
from app.db.session import get_db
from app.models.enums import Severity
from app.repositories import api_key as api_key_repo
from app.repositories import project as project_repo
from app.schemas.projects import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services import api_key as api_key_svc
from app.services import audit as audit_svc

router = APIRouter(prefix="/organizations/{org_id}/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await api_key_repo.list_for_org(db, ctx.org_id)


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    # If scoped to a project, verify it belongs to this org
    if body.project_id is not None:
        project = await project_repo.get_by_id_and_org(db, body.project_id, ctx.org_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found in this organization")

    api_key, full_key = await api_key_svc.create_api_key(
        db,
        organization_id=ctx.org_id,
        project_id=body.project_id,
        created_by_id=ctx.user.id,
        name=body.name,
        expires_at=body.expires_at,
    )

    scope = f"project:{body.project_id}" if body.project_id else "organization"
    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="api_key.created",
        entity_type="api_key",
        entity_id=str(api_key.id),
        message=f"API key '{body.name}' ({api_key.key_prefix}…) created, scope={scope}",
        severity=Severity.MEDIUM,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(api_key)

    # Embed the plaintext key in the response — shown exactly once, never stored
    return ApiKeyCreated(
        id=api_key.id,
        organization_id=api_key.organization_id,
        project_id=api_key.project_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        key=full_key,
    )


@router.post("/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_api_key(
    key_id: int,
    request: Request,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    api_key = await api_key_repo.get_by_id(db, key_id, ctx.org_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    from app.models.enums import ApiKeyStatus
    if api_key.status != ApiKeyStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="API key is already revoked or expired")

    await api_key_svc.revoke_api_key(
        db,
        api_key=api_key,
        revoked_by_id=ctx.user.id,
        organization_id=ctx.org_id,
    )
    await db.commit()
    await db.refresh(api_key)
    return api_key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: int,
    request: Request,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    api_key = await api_key_repo.get_by_id(db, key_id, ctx.org_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    name = api_key.name
    prefix = api_key.key_prefix
    await db.delete(api_key)
    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="api_key.deleted",
        entity_type="api_key",
        entity_id=str(key_id),
        message=f"API key '{name}' ({prefix}…) permanently deleted by {ctx.user.email}",
        severity=Severity.HIGH,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
