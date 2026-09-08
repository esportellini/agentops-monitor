"""
Pydantic schemas for request validation and response serialization.
One module per domain cluster — keeps the file navigable without artificial splitting.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.enums import (
    AgentStatus,
    AlertIncidentStatus,
    AlertRuleStatus,
    ApiKeyStatus,
    EnvironmentType,
    EvaluationStatus,
    MemberRole,
    ModelCallStatus,
    OrgPlan,
    PrivacyRequestStatus,
    PrivacyRequestType,
    Severity,
    SpanStatus,
    SpanType,
    ToolCallStatus,
    TraceStatus,
)


# ── Shared ─────────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Organization ───────────────────────────────────────────────────────────────

class OrganizationOut(OrmBase):
    id: int
    name: str
    slug: str
    plan: OrgPlan
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(BaseModel):
    name: str
    slug: str
    plan: OrgPlan = OrgPlan.FREE


# ── User ───────────────────────────────────────────────────────────────────────

class UserOut(OrmBase):
    id: int
    email: str
    name: str
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str


# ── OrganizationMember ─────────────────────────────────────────────────────────

class MemberOut(OrmBase):
    id: int
    organization_id: int
    user_id: int
    role: MemberRole
    created_at: datetime


# ── Project ────────────────────────────────────────────────────────────────────

class ProjectOut(OrmBase):
    id: int
    organization_id: int
    name: str
    slug: str
    description: str | None
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None


# ── Agent ──────────────────────────────────────────────────────────────────────

class AgentOut(OrmBase):
    id: int
    project_id: int
    name: str
    slug: str
    description: str | None
    version: str
    model_provider: str | None
    default_model: str | None
    status: AgentStatus
    created_at: datetime


class AgentCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    version: str = "0.1.0"
    model_provider: str | None = None
    default_model: str | None = None


# ── Environment ────────────────────────────────────────────────────────────────

class EnvironmentOut(OrmBase):
    id: int
    project_id: int
    name: str
    type: EnvironmentType
    created_at: datetime


# ── ApiKey ─────────────────────────────────────────────────────────────────────

class ApiKeyOut(OrmBase):
    """Returned for listing — never includes the full key or hash."""
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
    """Returned exactly once at creation. The `key` field is never stored."""
    key: str


class ApiKeyCreate(BaseModel):
    name: str
    project_id: int | None = None
    expires_at: datetime | None = None


# ── Trace ──────────────────────────────────────────────────────────────────────

class TraceOut(OrmBase):
    id: int
    organization_id: int
    project_id: int
    agent_id: int | None
    environment_id: int | None
    external_trace_id: str | None
    session_id: str | None
    name: str
    status: TraceStatus
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    unpriced_model_calls: int
    risk_level: Severity
    created_at: datetime


# ── Span ───────────────────────────────────────────────────────────────────────

class SpanOut(OrmBase):
    id: int
    trace_id: int
    parent_span_id: int | None
    name: str
    type: SpanType
    status: SpanStatus
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    input_data: dict | None
    output_data: dict | None
    error_data: dict | None
    created_at: datetime


# ── ToolCall ───────────────────────────────────────────────────────────────────

class ToolCallOut(OrmBase):
    id: int
    span_id: int
    tool_name: str
    input_data: dict | None
    output_data: dict | None
    status: ToolCallStatus
    duration_ms: int | None
    requires_approval: bool
    blocked_reason: str | None
    created_at: datetime


# ── ModelCall ──────────────────────────────────────────────────────────────────

class ModelCallOut(OrmBase):
    id: int
    span_id: int
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    occurred_at: datetime
    pricing_status: str
    pricing_id: int | None
    latency_ms: int | None
    temperature: float | None
    status: ModelCallStatus
    created_at: datetime


# ── SecurityFinding ────────────────────────────────────────────────────────────

class SecurityFindingOut(OrmBase):
    id: int
    organization_id: int
    trace_id: int | None
    finding_type: str
    severity: Severity
    title: str
    description: str
    resolved_at: datetime | None
    created_at: datetime


# ── AlertRule ──────────────────────────────────────────────────────────────────

class AlertRuleOut(OrmBase):
    id: int
    organization_id: int
    project_id: int | None
    name: str
    severity: Severity
    status: AlertRuleStatus
    condition: dict
    created_at: datetime


# ── AlertIncident ──────────────────────────────────────────────────────────────

class AlertIncidentOut(OrmBase):
    id: int
    rule_id: int
    status: AlertIncidentStatus
    triggered_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


# ── AuditLog ───────────────────────────────────────────────────────────────────

class AuditLogOut(OrmBase):
    id: int
    organization_id: int
    user_id: int | None
    event_type: str
    entity_type: str | None
    entity_id: str | None
    severity: Severity
    message: str
    created_at: datetime


# ── Update schemas (missing from original domain.py) ──────────────────────────

class OrganizationUpdate(BaseModel):
    name: str | None = None
    plan: OrgPlan | None = None


class MemberInvite(BaseModel):
    email: str
    role: MemberRole = MemberRole.VIEWER


class MemberRoleUpdate(BaseModel):
    role: MemberRole


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class EnvironmentUpdate(BaseModel):
    name: str | None = None
    type: EnvironmentType | None = None


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
