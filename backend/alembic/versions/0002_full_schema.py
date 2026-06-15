"""create full schema

Revision ID: 0002_full_schema
Revises: 0001_baseline
Create Date: 2024-01-02 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0002_full_schema"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE org_plan AS ENUM ('FREE','STARTER','GROWTH','ENTERPRISE')")
    op.execute("CREATE TYPE member_role AS ENUM ('OWNER','ADMIN','DEVELOPER','ANALYST','VIEWER')")
    op.execute("CREATE TYPE agent_status AS ENUM ('ACTIVE','INACTIVE','DEPRECATED')")
    op.execute("CREATE TYPE environment_type AS ENUM ('DEVELOPMENT','STAGING','PRODUCTION')")
    op.execute("CREATE TYPE api_key_status AS ENUM ('ACTIVE','REVOKED','EXPIRED')")
    op.execute("CREATE TYPE trace_status AS ENUM ('RUNNING','SUCCESS','ERROR','BLOCKED','CANCELLED')")
    op.execute("CREATE TYPE span_type AS ENUM ('AGENT','LLM','TOOL','RETRIEVAL','DATABASE','HTTP','VALIDATION','CUSTOM')")
    op.execute("CREATE TYPE span_status AS ENUM ('RUNNING','SUCCESS','ERROR')")
    op.execute("CREATE TYPE tool_call_status AS ENUM ('SUCCESS','ERROR','BLOCKED','PENDING_APPROVAL')")
    op.execute("CREATE TYPE model_call_status AS ENUM ('SUCCESS','ERROR','RATE_LIMITED','TIMEOUT')")
    op.execute("CREATE TYPE severity AS ENUM ('INFO','LOW','MEDIUM','HIGH','CRITICAL')")
    op.execute("CREATE TYPE evaluation_status AS ENUM ('PENDING','RUNNING','COMPLETED','FAILED')")
    op.execute("CREATE TYPE alert_rule_status AS ENUM ('ACTIVE','INACTIVE')")
    op.execute("CREATE TYPE alert_incident_status AS ENUM ('OPEN','ACKNOWLEDGED','RESOLVED')")
    op.execute("CREATE TYPE privacy_request_type AS ENUM ('EXPORT','DELETION','RECTIFICATION')")
    op.execute("CREATE TYPE privacy_request_status AS ENUM ('PENDING','IN_PROGRESS','COMPLETED','REJECTED')")

    # ── organizations ──────────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("plan", postgresql.ENUM("FREE", "STARTER", "GROWTH", "ENTERPRISE", name="org_plan", create_type=False), nullable=False, server_default="FREE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ── organization_members ───────────────────────────────────────────────────
    op.create_table(
        "organization_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invited_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role", postgresql.ENUM("OWNER", "ADMIN", "DEVELOPER", "ANALYST", "VIEWER", name="member_role", create_type=False), nullable=False, server_default="VIEWER"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
    )
    op.create_index("ix_org_members_org", "organization_members", ["organization_id"])
    op.create_index("ix_org_members_user", "organization_members", ["user_id"])

    # ── projects ───────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_project_slug"),
    )
    op.create_index("ix_projects_org", "projects", ["organization_id"])

    # ── agents ─────────────────────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(50), nullable=False, server_default="0.1.0"),
        sa.Column("model_provider", sa.String(100), nullable=True),
        sa.Column("default_model", sa.String(100), nullable=True),
        sa.Column("status", postgresql.ENUM("ACTIVE", "INACTIVE", "DEPRECATED", name="agent_status", create_type=False), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "slug", name="uq_agent_slug"),
    )
    op.create_index("ix_agents_project", "agents", ["project_id"])

    # ── environments ───────────────────────────────────────────────────────────
    op.create_table(
        "environments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", postgresql.ENUM("DEVELOPMENT", "STAGING", "PRODUCTION", name="environment_type", create_type=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_env_name"),
    )
    op.create_index("ix_environments_project", "environments", ["project_id"])

    # ── api_keys ───────────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revoked_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("status", postgresql.ENUM("ACTIVE", "REVOKED", "EXPIRED", name="api_key_status", create_type=False), nullable=False, server_default="ACTIVE"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_api_keys_org", "api_keys", ["organization_id"])
    op.create_index("ix_api_keys_project", "api_keys", ["project_id"])

    # ── traces ─────────────────────────────────────────────────────────────────
    op.create_table(
        "traces",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_trace_id", sa.String(255), nullable=True),
        sa.Column("session_id", sa.String(255), nullable=True),
        sa.Column("user_reference", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", postgresql.ENUM("RUNNING", "SUCCESS", "ERROR", "BLOCKED", "CANCELLED", name="trace_status", create_type=False), nullable=False, server_default="RUNNING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("total_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("risk_level", postgresql.ENUM("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", name="severity", create_type=False), nullable=False, server_default="INFO"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_traces_org", "traces", ["organization_id"])
    op.create_index("ix_traces_project", "traces", ["project_id"])
    op.create_index("ix_traces_agent", "traces", ["agent_id"])
    op.create_index("ix_traces_env", "traces", ["environment_id"])
    op.create_index("ix_traces_status", "traces", ["status"])
    op.create_index("ix_traces_external_id", "traces", ["external_trace_id"])
    op.create_index("ix_traces_session", "traces", ["session_id"])

    # ── spans ──────────────────────────────────────────────────────────────────
    op.create_table(
        "spans",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_span_id", sa.BigInteger(), sa.ForeignKey("spans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_span_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", postgresql.ENUM("AGENT", "LLM", "TOOL", "RETRIEVAL", "DATABASE", "HTTP", "VALIDATION", "CUSTOM", name="span_type", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM("RUNNING", "SUCCESS", "ERROR", name="span_status", create_type=False), nullable=False, server_default="RUNNING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("error_data", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_spans_trace", "spans", ["trace_id"])
    op.create_index("ix_spans_parent", "spans", ["parent_span_id"])
    op.create_index("ix_spans_type", "spans", ["type"])

    # ── tool_calls ─────────────────────────────────────────────────────────────
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("span_id", sa.BigInteger(), sa.ForeignKey("spans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("status", postgresql.ENUM("SUCCESS", "ERROR", "BLOCKED", "PENDING_APPROVAL", name="tool_call_status", create_type=False), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tool_calls_span", "tool_calls", ["span_id"])
    op.create_index("ix_tool_calls_name", "tool_calls", ["tool_name"])

    # ── model_calls ────────────────────────────────────────────────────────────
    op.create_table(
        "model_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("span_id", sa.BigInteger(), sa.ForeignKey("spans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("status", postgresql.ENUM("SUCCESS", "ERROR", "RATE_LIMITED", "TIMEOUT", name="model_call_status", create_type=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_calls_span", "model_calls", ["span_id"])
    op.create_index("ix_model_calls_provider", "model_calls", ["provider"])
    op.create_index("ix_model_calls_model", "model_calls", ["model"])

    # ── trace_events ───────────────────────────────────────────────────────────
    op.create_table(
        "trace_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("span_id", sa.BigInteger(), sa.ForeignKey("spans.id", ondelete="CASCADE"), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("severity", postgresql.ENUM("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", name="severity", create_type=False), nullable=False, server_default="INFO"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trace_events_trace", "trace_events", ["trace_id"])
    op.create_index("ix_trace_events_span", "trace_events", ["span_id"])
    op.create_index("ix_trace_events_type", "trace_events", ["event_type"])

    # ── cost_records ───────────────────────────────────────────────────────────
    op.create_table(
        "cost_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_call_id", sa.BigInteger(), sa.ForeignKey("model_calls.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(14, 8), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cost_records_org", "cost_records", ["organization_id"])
    op.create_index("ix_cost_records_trace", "cost_records", ["trace_id"])

    # ── security_findings ──────────────────────────────────────────────────────
    op.create_table(
        "security_findings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("traces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("span_id", sa.BigInteger(), sa.ForeignKey("spans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("finding_type", sa.String(100), nullable=False),
        sa.Column("severity", postgresql.ENUM("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", name="severity", create_type=False), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_security_findings_org", "security_findings", ["organization_id"])
    op.create_index("ix_security_findings_severity", "security_findings", ["severity"])

    # ── evaluation_datasets ────────────────────────────────────────────────────
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── evaluation_cases ───────────────────────────────────────────────────────
    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_data", postgresql.JSONB(), nullable=False),
        sa.Column("expected_output", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── evaluation_runs ────────────────────────────────────────────────────────
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("triggered_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", postgresql.ENUM("PENDING", "RUNNING", "COMPLETED", "FAILED", name="evaluation_status", create_type=False), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── evaluation_results ─────────────────────────────────────────────────────
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trace_id", sa.BigInteger(), sa.ForeignKey("traces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("actual_output", postgresql.JSONB(), nullable=True),
        sa.Column("evaluator_feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── alert_rules ────────────────────────────────────────────────────────────
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("condition", postgresql.JSONB(), nullable=False),
        sa.Column("severity", postgresql.ENUM("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", name="severity", create_type=False), nullable=False, server_default="MEDIUM"),
        sa.Column("status", postgresql.ENUM("ACTIVE", "INACTIVE", name="alert_rule_status", create_type=False), nullable=False, server_default="ACTIVE"),
        sa.Column("notification_channels", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_alert_rules_org", "alert_rules", ["organization_id"])

    # ── alert_incidents ────────────────────────────────────────────────────────
    op.create_table(
        "alert_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("acknowledged_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", postgresql.ENUM("OPEN", "ACKNOWLEDGED", "RESOLVED", name="alert_incident_status", create_type=False), nullable=False, server_default="OPEN"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── audit_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", sa.String(255), nullable=True),
        sa.Column("severity", postgresql.ENUM("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", name="severity", create_type=False), nullable=False, server_default="INFO"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("before_data", postgresql.JSONB(), nullable=True),
        sa.Column("after_data", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_org", "audit_logs", ["organization_id"])
    op.create_index("ix_audit_logs_user", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_created", "audit_logs", ["created_at"])

    # ── data_retention_policies ────────────────────────────────────────────────
    op.create_table(
        "data_retention_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("traces_retention_days", sa.Integer(), nullable=True, server_default="90"),
        sa.Column("spans_retention_days", sa.Integer(), nullable=True, server_default="90"),
        sa.Column("audit_logs_retention_days", sa.Integer(), nullable=True, server_default="365"),
        sa.Column("cost_records_retention_days", sa.Integer(), nullable=True),
        sa.Column("anonymize_user_references", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── privacy_requests ───────────────────────────────────────────────────────
    op.create_table(
        "privacy_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", postgresql.ENUM("EXPORT", "DELETION", "RECTIFICATION", name="privacy_request_type", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM("PENDING", "IN_PROGRESS", "COMPLETED", "REJECTED", name="privacy_request_status", create_type=False), nullable=False, server_default="PENDING"),
        sa.Column("subject_reference", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── system_settings ────────────────────────────────────────────────────────
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_system_settings_key", "system_settings", ["key"])


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_table("privacy_requests")
    op.drop_table("data_retention_policies")
    op.drop_table("audit_logs")
    op.drop_table("alert_incidents")
    op.drop_table("alert_rules")
    op.drop_table("evaluation_results")
    op.drop_table("evaluation_runs")
    op.drop_table("evaluation_cases")
    op.drop_table("evaluation_datasets")
    op.drop_table("security_findings")
    op.drop_table("cost_records")
    op.drop_table("trace_events")
    op.drop_table("model_calls")
    op.drop_table("tool_calls")
    op.drop_table("spans")
    op.drop_table("traces")
    op.drop_table("api_keys")
    op.drop_table("environments")
    op.drop_table("agents")
    op.drop_table("projects")
    op.drop_table("organization_members")
    op.drop_table("users")
    op.drop_table("organizations")

    op.execute("DROP TYPE IF EXISTS privacy_request_status")
    op.execute("DROP TYPE IF EXISTS privacy_request_type")
    op.execute("DROP TYPE IF EXISTS alert_incident_status")
    op.execute("DROP TYPE IF EXISTS alert_rule_status")
    op.execute("DROP TYPE IF EXISTS evaluation_status")
    op.execute("DROP TYPE IF EXISTS model_call_status")
    op.execute("DROP TYPE IF EXISTS tool_call_status")
    op.execute("DROP TYPE IF EXISTS severity")
    op.execute("DROP TYPE IF EXISTS span_status")
    op.execute("DROP TYPE IF EXISTS span_type")
    op.execute("DROP TYPE IF EXISTS trace_status")
    op.execute("DROP TYPE IF EXISTS api_key_status")
    op.execute("DROP TYPE IF EXISTS environment_type")
    op.execute("DROP TYPE IF EXISTS agent_status")
    op.execute("DROP TYPE IF EXISTS member_role")
    op.execute("DROP TYPE IF EXISTS org_plan")
