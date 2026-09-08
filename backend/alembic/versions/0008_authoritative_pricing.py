"""authoritative versioned pricing and cost provenance

Revision ID: 0008_authoritative_pricing
Revises: 0007_evaluations
Create Date: 2026-09-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_authoritative_pricing"
down_revision = "0007_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_model_pricing_lookup", table_name="model_pricing")
    op.add_column(
        "model_pricing", sa.Column("organization_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_model_pricing_organization",
        "model_pricing",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_model_pricing_organization_id",
        "model_pricing",
        ["organization_id"],
    )
    op.create_index(
        "ix_model_pricing_lookup",
        "model_pricing",
        ["organization_id", "provider", "model", "effective_from"],
    )

    op.add_column(
        "model_calls", sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "model_calls",
        sa.Column("pricing_status", sa.String(20), nullable=False, server_default="UNPRICED"),
    )
    op.add_column("model_calls", sa.Column("pricing_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_model_calls_pricing",
        "model_calls",
        "model_pricing",
        ["pricing_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_model_calls_pricing_id", "model_calls", ["pricing_id"])
    op.execute("UPDATE model_calls SET occurred_at = created_at WHERE occurred_at IS NULL")
    # Legacy client-supplied costs have no authoritative pricing provenance.
    op.execute("UPDATE model_calls SET estimated_cost = 0")
    op.alter_column("model_calls", "occurred_at", nullable=False)
    op.alter_column("model_calls", "pricing_status", server_default=None)

    op.add_column(
        "cost_records",
        sa.Column("pricing_status", sa.String(20), nullable=False, server_default="UNPRICED"),
    )
    op.add_column("cost_records", sa.Column("pricing_id", sa.Integer(), nullable=True))
    op.add_column(
        "cost_records",
        sa.Column("input_price_per_million", sa.Numeric(14, 8), nullable=True),
    )
    op.add_column(
        "cost_records",
        sa.Column("output_price_per_million", sa.Numeric(14, 8), nullable=True),
    )
    op.add_column(
        "cost_records",
        sa.Column("pricing_effective_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cost_records_pricing",
        "cost_records",
        "model_pricing",
        ["pricing_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_cost_records_pricing_id", "cost_records", ["pricing_id"])
    op.execute("UPDATE cost_records SET cost_usd = 0")
    op.alter_column("cost_records", "pricing_status", server_default=None)

    op.add_column(
        "traces",
        sa.Column(
            "unpriced_model_calls", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.execute(sa.text("""
        UPDATE traces
        SET unpriced_model_calls = counts.unpriced_count
        FROM (
            SELECT spans.trace_id, COUNT(*) AS unpriced_count
            FROM model_calls
            JOIN spans ON spans.id = model_calls.span_id
            WHERE model_calls.pricing_status = 'UNPRICED'
            GROUP BY spans.trace_id
        ) AS counts
        WHERE traces.id = counts.trace_id
    """))
    op.execute("UPDATE traces SET total_cost = 0")
    op.alter_column("traces", "unpriced_model_calls", server_default=None)


def downgrade() -> None:
    op.drop_column("traces", "unpriced_model_calls")

    op.drop_index("ix_cost_records_pricing_id", table_name="cost_records")
    op.drop_constraint("fk_cost_records_pricing", "cost_records", type_="foreignkey")
    op.drop_column("cost_records", "pricing_effective_from")
    op.drop_column("cost_records", "output_price_per_million")
    op.drop_column("cost_records", "input_price_per_million")
    op.drop_column("cost_records", "pricing_id")
    op.drop_column("cost_records", "pricing_status")

    op.drop_index("ix_model_calls_pricing_id", table_name="model_calls")
    op.drop_constraint("fk_model_calls_pricing", "model_calls", type_="foreignkey")
    op.drop_column("model_calls", "pricing_id")
    op.drop_column("model_calls", "pricing_status")
    op.drop_column("model_calls", "occurred_at")

    op.drop_index("ix_model_pricing_lookup", table_name="model_pricing")
    op.drop_index("ix_model_pricing_organization_id", table_name="model_pricing")
    op.drop_constraint(
        "fk_model_pricing_organization", "model_pricing", type_="foreignkey"
    )
    op.drop_column("model_pricing", "organization_id")
    op.create_index(
        "ix_model_pricing_lookup",
        "model_pricing",
        ["provider", "model", "effective_from"],
    )
