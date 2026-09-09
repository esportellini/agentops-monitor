"""evaluation provider runtime and pricing provenance

Revision ID: 0011_evaluation_provider_runtime
Revises: 0010_runtime_alerts
Create Date: 2026-09-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_evaluation_provider_runtime"
down_revision = "0010_runtime_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluation_runs", sa.Column("provider_api", sa.String(50), nullable=True))
    op.add_column("evaluation_runs", sa.Column("executed_cases", sa.Integer(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("error_cases", sa.Integer(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("unpriced_cases", sa.Integer(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("failure_reason", sa.Text(), nullable=True))

    op.add_column("evaluation_results", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("evaluation_results", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("evaluation_results", sa.Column("pricing_status", sa.String(20), nullable=True))
    op.add_column("evaluation_results", sa.Column("pricing_id", sa.Integer(), nullable=True))
    op.add_column("evaluation_results", sa.Column("input_price_per_million", sa.Numeric(14, 8), nullable=True))
    op.add_column("evaluation_results", sa.Column("output_price_per_million", sa.Numeric(14, 8), nullable=True))
    op.execute(
        "UPDATE evaluation_results AS result SET pricing_status = CASE "
        "WHEN result.error IS NOT NULL THEN 'ERROR' "
        "WHEN COALESCE(run.provider, 'mock') = 'mock' THEN 'MOCK' "
        "ELSE 'UNPRICED' END "
        "FROM evaluation_runs AS run WHERE run.id = result.run_id"
    )
    op.execute(
        "UPDATE evaluation_runs AS run SET "
        "executed_cases = (SELECT COUNT(*) FROM evaluation_results r WHERE r.run_id = run.id), "
        "error_cases = (SELECT COUNT(*) FROM evaluation_results r WHERE r.run_id = run.id AND r.error IS NOT NULL), "
        "unpriced_cases = (SELECT COUNT(*) FROM evaluation_results r WHERE r.run_id = run.id AND r.pricing_status = 'UNPRICED')"
    )
    op.execute(
        "DELETE FROM evaluation_results AS duplicate USING evaluation_results AS kept "
        "WHERE duplicate.run_id = kept.run_id AND duplicate.case_id = kept.case_id "
        "AND duplicate.id > kept.id"
    )
    op.create_index("ix_evaluation_results_pricing_id", "evaluation_results", ["pricing_id"])
    op.create_foreign_key(
        "fk_evaluation_results_pricing_id", "evaluation_results", "model_pricing",
        ["pricing_id"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_evaluation_result_run_case", "evaluation_results", ["run_id", "case_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_evaluation_result_run_case", "evaluation_results", type_="unique")
    op.drop_constraint("fk_evaluation_results_pricing_id", "evaluation_results", type_="foreignkey")
    op.drop_index("ix_evaluation_results_pricing_id", table_name="evaluation_results")
    for column in (
        "output_price_per_million", "input_price_per_million", "pricing_id",
        "pricing_status", "output_tokens", "input_tokens",
    ):
        op.drop_column("evaluation_results", column)
    for column in ("failure_reason", "unpriced_cases", "error_cases", "executed_cases", "provider_api"):
        op.drop_column("evaluation_runs", column)
