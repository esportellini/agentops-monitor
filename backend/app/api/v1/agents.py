from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_admin, require_developer, require_org_member
from app.db.session import get_db
from app.models.enums import AgentStatus, Severity
from app.models.project import Agent
from app.repositories import project as project_repo
from app.schemas.projects import (
    AgentCreate,
    AgentNewVersion,
    AgentOut,
    AgentStatusUpdate,
    AgentUpdate,
)
from app.services import audit as audit_svc

router = APIRouter(prefix="/organizations/{org_id}/agents", tags=["agents"])


def _bump_version(current: str) -> str:
    parts = current.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except (ValueError, IndexError):
        return f"{current}.1"


@router.get("", response_model=list[AgentOut])
async def list_agents(
    project_id: int | None = Query(default=None),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    return await project_repo.list_agents_for_org(db, ctx.org_id, project_id)


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    request: Request,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    # Validate project belongs to org
    project = await project_repo.get_by_id_and_org(db, body.project_id, ctx.org_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found in this organization")

    agent = Agent(
        project_id=body.project_id,
        owner_user_id=ctx.user.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        version=body.version,
        model_provider=body.model_provider,
        default_model=body.default_model,
        monthly_budget_usd=body.monthly_budget_usd,
        token_limit_per_trace=body.token_limit_per_trace,
        metadata_=body.metadata_,
        status=AgentStatus.ACTIVE,
    )
    db.add(agent)
    await db.flush()

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="agent.created",
        entity_type="agent",
        entity_id=str(agent.id),
        message=f"Agent '{agent.name}' v{agent.version} created in project '{project.name}'",
        severity=Severity.INFO,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    agent = await project_repo.get_agent_by_id(db, agent_id, ctx.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: int,
    body: AgentUpdate,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    agent = await project_repo.get_agent_by_id(db, agent_id, ctx.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(agent, field, value)

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="agent.updated",
        entity_type="agent",
        entity_id=str(agent_id),
        message=f"Agent '{agent.name}' updated",
        severity=Severity.INFO,
    )
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: int,
    request: Request,
    ctx: OrgContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    agent = await project_repo.get_agent_by_id(db, agent_id, ctx.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    name = agent.name
    await db.delete(agent)
    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="agent.deleted",
        entity_type="agent",
        entity_id=str(agent_id),
        message=f"Agent '{name}' permanently deleted by {ctx.user.email}",
        severity=Severity.HIGH,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()


@router.post("/{agent_id}/new-version", response_model=AgentOut)
async def bump_agent_version(
    agent_id: int,
    body: AgentNewVersion,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    agent = await project_repo.get_agent_by_id(db, agent_id, ctx.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    old_version = agent.version
    agent.version = body.version if body.version else _bump_version(agent.version)

    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="agent.version_bumped",
        entity_type="agent",
        entity_id=str(agent_id),
        message=f"Agent '{agent.name}' bumped {old_version} → {agent.version}",
        before_data={"version": old_version},
        after_data={"version": agent.version},
        severity=Severity.INFO,
    )
    await db.commit()
    await db.refresh(agent)
    return agent


@router.patch("/{agent_id}/status", response_model=AgentOut)
async def update_agent_status(
    agent_id: int,
    body: AgentStatusUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    agent = await project_repo.get_agent_by_id(db, agent_id, ctx.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    old_status = agent.status
    agent.status = body.status

    sev = Severity.HIGH if body.status == AgentStatus.ARCHIVED else Severity.MEDIUM
    await audit_svc.write(
        db,
        organization_id=ctx.org_id,
        user_id=ctx.user.id,
        event_type="agent.status_changed",
        entity_type="agent",
        entity_id=str(agent_id),
        message=f"Agent '{agent.name}' status changed {old_status} → {body.status}",
        before_data={"status": old_status.value},
        after_data={"status": body.status.value},
        severity=sev,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(agent)
    return agent
