from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.deps import OrgContext, require_admin, require_developer, require_org_member
from app.db.session import get_db
from app.models.enums import Severity
from app.models.project import Environment
from app.repositories import project as project_repo
from app.schemas.projects import EnvironmentCreate, EnvironmentOut, EnvironmentUpdate
from app.services import audit as audit_svc

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/environments",
    tags=["environments"],
)


@router.get("", response_model=list[EnvironmentOut])
async def list_environments(
    project_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    project = await project_repo.get_by_id_and_org(db, project_id, ctx.org_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await db.execute(
        select(Environment)
        .where(Environment.project_id == project_id)
        .order_by(Environment.created_at)
    )
    return result.scalars().all()


@router.post("", response_model=EnvironmentOut, status_code=status.HTTP_201_CREATED)
async def create_environment(
    project_id: int,
    body: EnvironmentCreate,
    request: Request,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    project = await project_repo.get_by_id_and_org(db, project_id, ctx.org_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    env = Environment(project_id=project_id, name=body.name, type=body.type)
    db.add(env)
    await db.flush()

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="environment.created",
        entity_type="environment",
        entity_id=str(env.id),
        message=f"Environment '{env.name}' ({env.type}) created in project '{project.name}'",
        severity=Severity.INFO,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(env)
    return env


@router.patch("/{env_id}", response_model=EnvironmentOut)
async def update_environment(
    project_id: int,
    env_id: int,
    body: EnvironmentUpdate,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    env = await project_repo.get_environment_by_id(db, env_id, ctx.org_id)
    if not env or env.project_id != project_id:
        raise HTTPException(status_code=404, detail="Environment not found")

    if body.name is not None:
        env.name = body.name
    if body.type is not None:
        env.type = body.type

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="environment.updated",
        entity_type="environment",
        entity_id=str(env_id),
        message=f"Environment '{env.name}' updated",
        severity=Severity.INFO,
    )
    await db.commit()
    await db.refresh(env)
    return env


@router.delete("/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    project_id: int,
    env_id: int,
    request: Request,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    env = await project_repo.get_environment_by_id(db, env_id, ctx.org_id)
    if not env or env.project_id != project_id:
        raise HTTPException(status_code=404, detail="Environment not found")

    name = env.name
    await db.delete(env)
    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="environment.deleted",
        entity_type="environment",
        entity_id=str(env_id),
        message=f"Environment '{name}' deleted by {ctx.user.email}",
        severity=Severity.MEDIUM,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
