"""add brute force columns to users

Revision ID: 0003_auth_columns
Revises: 0002_full_schema
Create Date: 2024-01-03 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_auth_columns"
down_revision = "0002_full_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
