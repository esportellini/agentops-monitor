"""runtime alert rules and incident provenance

Revision ID: 0010_runtime_alerts
Revises: 0009_tool_approval_runtime
Create Date: 2026-09-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_runtime_alerts"
down_revision = "0009_tool_approval_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_rules", sa.Column("event_type", sa.String(64), nullable=True))
    op.add_column("alert_rules", sa.Column("agent_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE alert_rules SET event_type = CASE "
        "WHEN condition->>'metric' IN ('finding_type', 'severity', 'action_taken') "
        "THEN 'security.finding.created' "
        "ELSE 'trace.finished' END"
    )
    op.execute(
        "UPDATE alert_rules SET status = 'INACTIVE' "
        "WHERE COALESCE(condition->>'metric', '') NOT IN ("
        "'event_type', 'finding_type', 'severity', 'action_taken', "
        "'trace_status', 'risk_level', 'total_cost_usd', 'cost_usd', "
        "'total_tokens', 'token_count', 'duration_ms', 'latency_ms', "
        "'unpriced_model_calls')"
    )
    op.alter_column("alert_rules", "event_type", nullable=False)
    op.create_index("ix_alert_rules_event_type", "alert_rules", ["event_type"])
    op.create_index("ix_alert_rules_agent_id", "alert_rules", ["agent_id"])
    op.create_foreign_key(
        "fk_alert_rules_agent_id", "alert_rules", "agents", ["agent_id"], ["id"],
        ondelete="CASCADE",
    )

    op.add_column("alert_incidents", sa.Column("event_type", sa.String(64), nullable=True))
    op.add_column("alert_incidents", sa.Column("source_type", sa.String(64), nullable=True))
    op.add_column("alert_incidents", sa.Column("source_id", sa.String(255), nullable=True))
    op.add_column("alert_incidents", sa.Column("trace_id", sa.BigInteger(), nullable=True))
    op.add_column("alert_incidents", sa.Column("project_id", sa.Integer(), nullable=True))
    op.add_column("alert_incidents", sa.Column("agent_id", sa.Integer(), nullable=True))
    op.add_column("alert_incidents", sa.Column("severity", postgresql.ENUM(
        "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", name="severity",
        create_type=False,
    ), nullable=True))
    op.add_column("alert_incidents", sa.Column("dedupe_key", sa.String(255), nullable=True))
    op.execute(
        "UPDATE alert_incidents AS i SET severity = r.severity "
        "FROM alert_rules AS r WHERE r.id = i.rule_id"
    )
    op.alter_column("alert_incidents", "severity", nullable=False)
    op.create_index("ix_alert_incidents_event_type", "alert_incidents", ["event_type"])
    op.create_index("ix_alert_incidents_trace_id", "alert_incidents", ["trace_id"])
    op.create_index("ix_alert_incidents_project_id", "alert_incidents", ["project_id"])
    op.create_index("ix_alert_incidents_agent_id", "alert_incidents", ["agent_id"])
    op.create_index("ix_alert_incidents_severity", "alert_incidents", ["severity"])
    op.create_unique_constraint(
        "uq_alert_incident_dedupe_key", "alert_incidents", ["dedupe_key"]
    )
    op.create_foreign_key(
        "fk_alert_incidents_trace_id", "alert_incidents", "traces", ["trace_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_alert_incidents_project_id", "alert_incidents", "projects",
        ["project_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_alert_incidents_agent_id", "alert_incidents", "agents", ["agent_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_alert_incidents_agent_id", "alert_incidents", type_="foreignkey")
    op.drop_constraint("fk_alert_incidents_project_id", "alert_incidents", type_="foreignkey")
    op.drop_constraint("fk_alert_incidents_trace_id", "alert_incidents", type_="foreignkey")
    op.drop_constraint("uq_alert_incident_dedupe_key", "alert_incidents", type_="unique")
    for name in (
        "ix_alert_incidents_severity", "ix_alert_incidents_agent_id",
        "ix_alert_incidents_project_id", "ix_alert_incidents_trace_id",
        "ix_alert_incidents_event_type",
    ):
        op.drop_index(name, table_name="alert_incidents")
    for name in (
        "dedupe_key", "severity", "agent_id", "project_id", "trace_id",
        "source_id", "source_type", "event_type",
    ):
        op.drop_column("alert_incidents", name)
    op.drop_constraint("fk_alert_rules_agent_id", "alert_rules", type_="foreignkey")
    op.drop_index("ix_alert_rules_agent_id", table_name="alert_rules")
    op.drop_index("ix_alert_rules_event_type", table_name="alert_rules")
    op.drop_column("alert_rules", "agent_id")
    op.drop_column("alert_rules", "event_type")
