"""Helpers for building test fixtures — not a framework, just functions."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.enums import MemberRole, OrgPlan
from app.models.organization import Organization, OrganizationMember, User


async def make_user(
    db: AsyncSession,
    email: str = "test@example.com",
    name: str = "Test User",
    password: str = "password123",
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        name=name,
        password_hash=hash_password(password),
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


async def make_org(
    db: AsyncSession,
    name: str = "Test Org",
    slug: str = "test-org",
    plan: OrgPlan = OrgPlan.FREE,
) -> Organization:
    org = Organization(name=name, slug=slug, plan=plan)
    db.add(org)
    await db.flush()
    return org


async def make_member(
    db: AsyncSession,
    org: Organization,
    user: User,
    role: MemberRole = MemberRole.VIEWER,
) -> OrganizationMember:
    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=role,
    )
    db.add(member)
    await db.flush()
    return member


async def make_user_with_org(
    db: AsyncSession,
    email: str = "owner@example.com",
    role: MemberRole = MemberRole.OWNER,
    org_slug: str = "test-org",
) -> tuple[User, Organization, OrganizationMember]:
    user = await make_user(db, email=email)
    org = await make_org(db, slug=org_slug)
    member = await make_member(db, org, user, role=role)
    return user, org, member


# ── Project / Agent / Env factories ───────────────────────────────────────────

from app.models.enums import AgentStatus, EnvironmentType
from app.models.project import Agent, Environment, Project


async def make_project(
    db: AsyncSession,
    org: Organization,
    name: str = "Test Project",
    slug: str = "test-project",
) -> Project:
    project = Project(organization_id=org.id, name=name, slug=slug)
    db.add(project)
    await db.flush()
    return project


async def make_agent(
    db: AsyncSession,
    project: Project,
    name: str = "Test Agent",
    slug: str = "test-agent",
    version: str = "1.0.0",
    status: AgentStatus = AgentStatus.ACTIVE,
) -> Agent:
    agent = Agent(
        project_id=project.id,
        name=name,
        slug=slug,
        version=version,
        status=status,
    )
    db.add(agent)
    await db.flush()
    return agent


async def make_environment(
    db: AsyncSession,
    project: Project,
    name: str = "development",
    env_type: EnvironmentType = EnvironmentType.DEVELOPMENT,
) -> Environment:
    env = Environment(project_id=project.id, name=name, type=env_type)
    db.add(env)
    await db.flush()
    return env


# ── API key factory for ingest tests ──────────────────────────────────────────

from app.models.api_key import ApiKey
from app.models.enums import ApiKeyStatus
from app.services.api_key import generate_api_key


async def make_api_key(
    db: AsyncSession,
    org: Organization,
    project: "Project | None" = None,
    name: str = "Test key",
) -> tuple[ApiKey, str]:
    """Returns (ApiKey ORM, full plaintext key)."""
    full_key, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        organization_id=org.id,
        project_id=project.id if project else None,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        status=ApiKeyStatus.ACTIVE,
    )
    db.add(api_key)
    await db.flush()
    return api_key, full_key
