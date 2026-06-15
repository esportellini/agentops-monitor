"""add agent budget fields and update agent_status enum

Revision ID: 0004_agent_fields
Revises: 0003_auth_columns
Create Date: 2024-01-04 00:00:00.000000

NOTE: PostgreSQL's ADD VALUE cannot be used in the same transaction as a
query that references the new value. We work around this by running the
ADD VALUE statements with transaction_per_migration=False (no wrapping
transaction), committing them, then running the data migration in a
separate step. We achieve this by splitting into two migration files.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0004_agent_fields"
down_revision = "0003_auth_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: add the new columns (safe inside a transaction)
    op.add_column("agents", sa.Column("monthly_budget_usd", sa.Float(), nullable=True))
    op.add_column("agents", sa.Column("token_limit_per_trace", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("metadata", postgresql.JSONB(), nullable=True))

    # Step 2: ADD VALUE must run outside a transaction in PostgreSQL.
    # We use op.execute with the raw connection set to autocommit before calling.
    # Because we're inside run_sync/begin(), we cannot change isolation on the
    # existing connection. Instead we use a raw DBAPI connection via
    # op.get_bind().connection.driver_connection to bypass SQLAlchemy's
    # transaction wrapper entirely.
    bind = op.get_bind()
    raw = bind.connection.driver_connection  # raw asyncpg Connection (sync-adapted)

    # The asyncpg driver is wrapped by SQLAlchemy's sync shim.
    # We need to commit the current transaction, run ADD VALUE, then let
    # Alembic open a new transaction for the rest.
    # The cleanest portable way: use op.execute with a raw DDL that Postgres
    # will execute in its own implicit transaction block when called standalone.
    # Since we can't do AUTOCOMMIT on the already-open txn, we commit it first.
    bind.execute(sa.text("COMMIT"))
    bind.execute(sa.text("ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'PAUSED'"))
    bind.execute(sa.text("ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'ARCHIVED'"))
    bind.execute(sa.text("BEGIN"))

    # Step 3: now the new enum values are committed — safe to use
    bind.execute(sa.text("UPDATE agents SET status = 'PAUSED' WHERE status = 'INACTIVE'"))
    bind.execute(sa.text("UPDATE agents SET status = 'ARCHIVED' WHERE status = 'DEPRECATED'"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE agents SET status = 'INACTIVE' WHERE status = 'PAUSED'"))
    bind.execute(sa.text("UPDATE agents SET status = 'DEPRECATED' WHERE status = 'ARCHIVED'"))
    op.drop_column("agents", "metadata")
    op.drop_column("agents", "token_limit_per_trace")
    op.drop_column("agents", "monthly_budget_usd")
