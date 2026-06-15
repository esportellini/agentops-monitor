"""add model_pricing table with seed prices

Revision ID: 0005_model_pricing
Revises: 0004_agent_fields
Create Date: 2024-01-05 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0005_model_pricing"
down_revision = "0004_agent_fields"
branch_labels = None
depends_on = None

# Seed prices as of 2024-01 (USD per million tokens)
# Source: official provider pricing pages
_SEED_PRICES = [
    # OpenAI
    ("openai", "gpt-4o",                   2.50,   10.00),
    ("openai", "gpt-4o-mini",              0.15,    0.60),
    ("openai", "gpt-4o-2024-11-20",        2.50,   10.00),
    ("openai", "gpt-4-turbo",             10.00,   30.00),
    ("openai", "gpt-3.5-turbo",            0.50,    1.50),
    ("openai", "text-embedding-3-small",   0.02,    0.00),
    ("openai", "text-embedding-3-large",   0.13,    0.00),
    # Anthropic
    ("anthropic", "claude-3-5-sonnet-20241022", 3.00, 15.00),
    ("anthropic", "claude-3-5-haiku-20241022",  0.80,  4.00),
    ("anthropic", "claude-3-opus-20240229",     15.00, 75.00),
    ("anthropic", "claude-3-sonnet-20240229",    3.00, 15.00),
    ("anthropic", "claude-3-haiku-20240307",     0.25,  1.25),
    ("anthropic", "claude-sonnet-4-6",           3.00, 15.00),
    ("anthropic", "claude-opus-4-6",            15.00, 75.00),
    # Google
    ("google", "gemini-1.5-pro",           1.25,   5.00),
    ("google", "gemini-1.5-flash",         0.075,  0.30),
    ("google", "gemini-1.5-flash-8b",      0.0375, 0.15),
    # Meta / Groq
    ("groq", "llama-3.1-70b-versatile",    0.59,   0.79),
    ("groq", "llama-3.1-8b-instant",       0.05,   0.08),
    # Mistral
    ("mistral", "mistral-large-latest",    2.00,   6.00),
    ("mistral", "mistral-small-latest",    0.20,   0.60),
]


def upgrade() -> None:
    op.create_table(
        "model_pricing",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_price_per_million", sa.Numeric(14, 8), nullable=False),
        sa.Column("output_price_per_million", sa.Numeric(14, 8), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_model_pricing_lookup", "model_pricing", ["provider", "model", "effective_from"])
    op.create_index("ix_model_pricing_provider", "model_pricing", ["provider"])
    op.create_index("ix_model_pricing_model", "model_pricing", ["model"])

    # Seed with well-known prices
    bind = op.get_bind()
    for provider, model, inp, out in _SEED_PRICES:
        bind.execute(sa.text("""
            INSERT INTO model_pricing
              (provider, model, input_price_per_million, output_price_per_million,
               effective_from, active)
            VALUES
              (:provider, :model, :inp, :out,
               '2024-01-01T00:00:00+00:00', true)
        """), {"provider": provider, "model": model, "inp": inp, "out": out})

    # Add index on cost_records.recorded_at for timeseries queries
    op.create_index(
        "ix_cost_records_org_recorded_at",
        "cost_records",
        ["organization_id", "recorded_at"],
    )

    # Add index on traces.started_at for time-range aggregations
    op.create_index(
        "ix_traces_org_started_at",
        "traces",
        ["organization_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_traces_org_started_at", table_name="traces")
    op.drop_index("ix_cost_records_org_recorded_at", table_name="cost_records")
    op.drop_index("ix_model_pricing_model", table_name="model_pricing")
    op.drop_index("ix_model_pricing_provider", table_name="model_pricing")
    op.drop_index("ix_model_pricing_lookup", table_name="model_pricing")
    op.drop_table("model_pricing")
