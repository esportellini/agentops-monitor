from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_admin, require_developer, require_org_member
from app.db.session import get_db
from app.models.enums import Severity
from app.models.project import Project
from app.repositories import project as project_repo
from app.schemas.projects import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import audit as audit_svc

router = APIRouter(prefix="/organizations/{org_id}/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await project_repo.list_for_org(db, ctx.org_id)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    request: Request,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    if await project_repo.get_by_slug(db, ctx.org_id, body.slug):
        raise HTTPException(status_code=409, detail="Slug already in use in this organization")

    project = Project(
        organization_id=ctx.org_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
    )
    db.add(project)
    await db.flush()

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="project.created",
        entity_type="project",
        entity_id=str(project.id),
        message=f"Project '{project.name}' created by {ctx.user.email}",
        severity=Severity.INFO,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    project = await project_repo.get_by_id_and_org(db, project_id, ctx.org_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    project = await project_repo.get_by_id_and_org(db, project_id, ctx.org_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="project.updated",
        entity_type="project",
        entity_id=str(project.id),
        message=f"Project '{project.name}' updated",
        severity=Severity.INFO,
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    request: Request,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    project = await project_repo.get_by_id_and_org(db, project_id, ctx.org_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_name = project.name
    await db.delete(project)
    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="project.deleted",
        entity_type="project",
        entity_id=str(project_id),
        message=f"Project '{project_name}' deleted by {ctx.user.email}",
        severity=Severity.HIGH,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
