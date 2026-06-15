"""expand evaluation tables — add missing columns

Revision ID: 0007_evaluations
Revises: 0006_security
Create Date: 2024-01-07 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op
from sqlalchemy import text

revision = "0007_evaluations"
down_revision = "0006_security"
branch_labels = None
depends_on = None


def _col_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": col})
    return r.fetchone() is not None


def upgrade() -> None:
    # ── evaluation_datasets ───────────────────────────────────────────────────
    if not _col_exists("evaluation_datasets", "version"):
        op.add_column("evaluation_datasets", sa.Column("version", sa.String(50), nullable=False, server_default="1.0.0"))
    if not _col_exists("evaluation_datasets", "tags"):
        op.add_column("evaluation_datasets", sa.Column("tags", postgresql.JSONB(), nullable=True))

    # project_id may be NOT NULL in old schema — relax to nullable
    try:
        op.alter_column("evaluation_datasets", "project_id", nullable=True)
    except Exception:
        pass

    # ── evaluation_cases ──────────────────────────────────────────────────────
    if not _col_exists("evaluation_cases", "expected_tools"):
        op.add_column("evaluation_cases", sa.Column("expected_tools", postgresql.JSONB(), nullable=True))
    if not _col_exists("evaluation_cases", "tags"):
        op.add_column("evaluation_cases", sa.Column("tags", postgresql.JSONB(), nullable=True))
    if not _col_exists("evaluation_cases", "metadata"):
        op.add_column("evaluation_cases", sa.Column("metadata", postgresql.JSONB(), nullable=True))

    # ── evaluation_runs ───────────────────────────────────────────────────────
    for col, typ in [
        ("organization_id", sa.Integer()),
        ("agent_id", sa.Integer()),
        ("agent_version", sa.String(100)),
        ("provider", sa.String(100)),
        ("model", sa.String(100)),
        ("prompt_version", sa.String(100)),
        ("total_cost", sa.Float()),
        ("average_latency_ms", sa.Float()),
        ("pass_rate", sa.Float()),
        ("average_score", sa.Float()),
        ("total_cases", sa.Integer()),
        ("passed_cases", sa.Integer()),
        ("config", postgresql.JSONB()),
    ]:
        if not _col_exists("evaluation_runs", col):
            op.add_column("evaluation_runs", sa.Column(col, typ, nullable=True))

    # Back-fill organization_id from dataset
    op.execute(text("""
        UPDATE evaluation_runs r
        SET organization_id = d.organization_id
        FROM evaluation_datasets d
        WHERE r.dataset_id = d.id
          AND r.organization_id IS NULL
    """))

    # Add FK for organization_id and agent_id if not exist
    try:
        op.create_foreign_key("fk_erun_org", "evaluation_runs", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
    except Exception:
        pass
    try:
        op.create_foreign_key("fk_erun_agent", "evaluation_runs", "agents", ["agent_id"], ["id"], ondelete="SET NULL")
    except Exception:
        pass

    op.create_index("ix_evaluation_runs_org", "evaluation_runs", ["organization_id"], if_not_exists=True)

    # ── evaluation_results ────────────────────────────────────────────────────
    for col, typ in [
        ("actual_tools_used", postgresql.JSONB()),
        ("latency_ms", sa.Integer()),
        ("cost", sa.Float()),
        ("evaluator_details", postgresql.JSONB()),
        ("error", sa.Text()),
        ("human_review_status", sa.String(20)),
        ("human_review_note", sa.Text()),
        ("reviewed_by_id", sa.Integer()),
        ("reviewed_at", sa.DateTime(timezone=True)),
    ]:
        if not _col_exists("evaluation_results", col):
            op.add_column("evaluation_results", sa.Column(col, typ, nullable=True))

    # Rename evaluator_feedback → evaluator_details if old column exists
    if _col_exists("evaluation_results", "evaluator_feedback") and not _col_exists("evaluation_results", "evaluator_details"):
        op.alter_column("evaluation_results", "evaluator_feedback", new_column_name="evaluator_details")

    try:
        op.create_foreign_key("fk_eresult_reviewer", "evaluation_results", "users", ["reviewed_by_id"], ["id"], ondelete="SET NULL")
    except Exception:
        pass

    op.create_index("ix_evaluation_results_case", "evaluation_results", ["case_id"], if_not_exists=True)


def downgrade() -> None:
    pass  # non-destructive — columns added, not tables dropped
