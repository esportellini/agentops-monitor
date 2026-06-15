from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AgentStatus, EnvironmentType

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.api_key import ApiKey
    from app.models.trace import Trace


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_project_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    agents: Mapped[list[Agent]] = relationship(back_populates="project", cascade="all, delete-orphan")
    environments: Mapped[list[Environment]] = relationship(back_populates="project", cascade="all, delete-orphan")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="project")
    traces: Mapped[list[Trace]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_agent_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="0.1.0")
    model_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"), nullable=False, default=AgentStatus.ACTIVE
    )
    # Budget / limits
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_limit_per_trace: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    project: Mapped[Project] = relationship(back_populates="agents")
    traces: Mapped[list[Trace]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class Environment(Base, TimestampMixin):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_env_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[EnvironmentType] = mapped_column(
        Enum(EnvironmentType, name="environment_type"), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="environments")
    traces: Mapped[list[Trace]] = relationship(back_populates="environment")
