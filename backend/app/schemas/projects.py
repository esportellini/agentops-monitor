import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.enums import AgentStatus, ApiKeyStatus, EnvironmentType


class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _slug_validator(v: str) -> str:
    if not re.match(r"^[a-z0-9-]+$", v):
        raise ValueError("slug must be lowercase alphanumeric with hyphens only")
    return v


# ── Project ────────────────────────────────────────────────────────────────────

class ProjectOut(OrmBase):
    id: int
    organization_id: int
    name: str
    slug: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        return _slug_validator(v)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


# ── Environment ────────────────────────────────────────────────────────────────

class EnvironmentOut(OrmBase):
    id: int
    project_id: int
    name: str
    type: EnvironmentType
    created_at: datetime


class EnvironmentCreate(BaseModel):
    name: str
    type: EnvironmentType


class EnvironmentUpdate(BaseModel):
    name: str | None = None
    type: EnvironmentType | None = None


# ── Agent ──────────────────────────────────────────────────────────────────────

class AgentOut(OrmBase):
    id: int
    project_id: int
    owner_user_id: int | None
    name: str
    slug: str
    description: str | None
    version: str
    model_provider: str | None
    default_model: str | None
    status: AgentStatus
    monthly_budget_usd: float | None
    token_limit_per_trace: int | None
    metadata_: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AgentCreate(BaseModel):
    project_id: int
    name: str
    slug: str
    description: str | None = None
    version: str = "0.1.0"
    model_provider: str | None = None
    default_model: str | None = None
    monthly_budget_usd: float | None = None
    token_limit_per_trace: int | None = None
    metadata_: dict | None = None

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        return _slug_validator(v)


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    model_provider: str | None = None
    default_model: str | None = None
    monthly_budget_usd: float | None = None
    token_limit_per_trace: int | None = None
    metadata_: dict | None = None
    owner_user_id: int | None = None


class AgentStatusUpdate(BaseModel):
    status: AgentStatus


class AgentNewVersion(BaseModel):
    version: str = ""


# ── ApiKey ─────────────────────────────────────────────────────────────────────

class ApiKeyOut(OrmBase):
    """Safe to return in list endpoints — never includes hash."""
    id: int
    organization_id: int
    project_id: int | None
    name: str
    key_prefix: str
    status: ApiKeyStatus
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    """Returned exactly once at creation time. key is shown once and never stored."""
    key: str


class ApiKeyCreate(BaseModel):
    name: str
    project_id: int | None = None
    expires_at: datetime | None = None
