from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Agent, Environment, Project


async def get_by_id(db: AsyncSession, project_id: int) -> Project | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def get_by_id_and_org(db: AsyncSession, project_id: int, org_id: int) -> Project | None:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.organization_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_by_slug(db: AsyncSession, org_id: int, slug: str) -> Project | None:
    result = await db.execute(
        select(Project).where(Project.organization_id == org_id, Project.slug == slug)
    )
    return result.scalar_one_or_none()


async def list_for_org(db: AsyncSession, org_id: int) -> list[Project]:
    result = await db.execute(
        select(Project).where(Project.organization_id == org_id).order_by(Project.name)
    )
    return list(result.scalars().all())


async def get_agent_by_id(db: AsyncSession, agent_id: int, org_id: int) -> Agent | None:
    """Validates org membership via project join."""
    result = await db.execute(
        select(Agent)
        .join(Project, Project.id == Agent.project_id)
        .where(Agent.id == agent_id, Project.organization_id == org_id)
    )
    return result.scalar_one_or_none()


async def list_agents_for_org(db: AsyncSession, org_id: int, project_id: int | None = None) -> list[Agent]:
    q = (
        select(Agent)
        .join(Project, Project.id == Agent.project_id)
        .where(Project.organization_id == org_id)
    )
    if project_id is not None:
        q = q.where(Agent.project_id == project_id)
    q = q.order_by(Agent.name)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_environment_by_id(db: AsyncSession, env_id: int, org_id: int) -> Environment | None:
    result = await db.execute(
        select(Environment)
        .join(Project, Project.id == Environment.project_id)
        .where(Environment.id == env_id, Project.organization_id == org_id)
    )
    return result.scalar_one_or_none()
