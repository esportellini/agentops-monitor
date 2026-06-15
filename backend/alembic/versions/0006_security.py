"""add agent_policies, tool_approvals, security findings enhancements

Revision ID: 0006_security
Revises: 0005_model_pricing
Create Date: 2024-01-06 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op
from sqlalchemy import text, inspect

revision = "0006_security"
down_revision = "0005_model_pricing"
branch_labels = None
depends_on = None


def _col_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": col})
    return result.fetchone() is not None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name=:t"
    ), {"t": table})
    return result.fetchone() is not None


def upgrade() -> None:
    # ── Enhance security_findings ────────────────────────────────────────────
    if not _col_exists("security_findings", "agent_id"):
        op.add_column("security_findings", sa.Column("agent_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_security_findings_agent_id",
            "security_findings", "agents", ["agent_id"], ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_security_findings_agent_id", "security_findings", ["agent_id"])

    if not _col_exists("security_findings", "action_taken"):
        op.add_column("security_findings", sa.Column(
            "action_taken", sa.String(50), nullable=False, server_default="detect"
        ))
    if not _col_exists("security_findings", "redacted_content"):
        op.add_column("security_findings", sa.Column("redacted_content", sa.Text(), nullable=True))
    if not _col_exists("security_findings", "resolution_note"):
        op.add_column("security_findings", sa.Column("resolution_note", sa.Text(), nullable=True))

    # ── agent_policies ────────────────────────────────────────────────────────
    if not _table_exists("agent_policies"):
        op.create_table(
            "agent_policies",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False, unique=True),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("allowed_tools", postgresql.JSONB(), nullable=True),
            sa.Column("blocked_tools", postgresql.JSONB(), nullable=True),
            sa.Column("tools_requiring_approval", postgresql.JSONB(), nullable=True),
            sa.Column("max_tokens_per_trace", sa.Integer(), nullable=True),
            sa.Column("max_cost_per_trace_usd", sa.Float(), nullable=True),
            sa.Column("allowed_domains", postgresql.JSONB(), nullable=True),
            sa.Column("blocked_domains", postgresql.JSONB(), nullable=True),
            sa.Column("capture_inputs", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("capture_outputs", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("pii_action", sa.String(20), nullable=False, server_default="alert"),
            sa.Column("secret_action", sa.String(20), nullable=False, server_default="block"),
            sa.Column("injection_action", sa.String(20), nullable=False, server_default="alert"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_agent_policies_org", "agent_policies", ["organization_id"])
        op.create_index("ix_agent_policies_agent", "agent_policies", ["agent_id"])

    # ── tool_approvals ────────────────────────────────────────────────────────
    if not _table_exists("tool_approvals"):
        op.create_table(
            "tool_approvals",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("trace_id", sa.BigInteger(), nullable=True),
            sa.Column("span_id", sa.BigInteger(), nullable=True),
            sa.Column("agent_id", sa.Integer(), nullable=True),
            sa.Column("requested_by_id", sa.Integer(), nullable=True),
            sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
            sa.Column("tool_name", sa.String(255), nullable=False),
            sa.Column("tool_input", postgresql.JSONB(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["trace_id"], ["traces.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["span_id"], ["spans.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_tool_approvals_org", "tool_approvals", ["organization_id"])
        op.create_index("ix_tool_approvals_status", "tool_approvals", ["status"])
        op.create_index("ix_tool_approvals_trace", "tool_approvals", ["trace_id"])

    # ── alert_incidents: resolution_note ──────────────────────────────────────
    if not _col_exists("alert_incidents", "resolution_note"):
        op.add_column("alert_incidents", sa.Column("resolution_note", sa.Text(), nullable=True))


def downgrade() -> None:
    if _table_exists("tool_approvals"):
        op.drop_table("tool_approvals")
    if _table_exists("agent_policies"):
        op.drop_table("agent_policies")
    if _col_exists("security_findings", "agent_id"):
        op.drop_index("ix_security_findings_agent_id", "security_findings")
        op.drop_constraint("fk_security_findings_agent_id", "security_findings", type_="foreignkey")
        op.drop_column("security_findings", "agent_id")
    for col in ("resolution_note", "redacted_content", "action_taken"):
        if _col_exists("security_findings", col):
            op.drop_column("security_findings", col)
    if _col_exists("alert_incidents", "resolution_note"):
        op.drop_column("alert_incidents", "resolution_note")
