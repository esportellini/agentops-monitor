"""one-time human tool approval runtime

Revision ID: 0009_tool_approval_runtime
Revises: 0008_authoritative_pricing
Create Date: 2026-09-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_tool_approval_runtime"
down_revision = "0008_authoritative_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_approvals", sa.Column("external_request_id", sa.String(255), nullable=True))
    op.add_column("tool_approvals", sa.Column("target_url", sa.String(2048), nullable=True))
    op.add_column("tool_approvals", sa.Column("used_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE tool_approvals SET external_request_id = "
        "'legacy-' || organization_id::text || '-' || id::text "
        "WHERE external_request_id IS NULL"
    )
    op.alter_column("tool_approvals", "external_request_id", nullable=False)
    op.create_index(
        "ix_tool_approvals_external_request_id", "tool_approvals", ["external_request_id"]
    )
    op.create_unique_constraint(
        "uq_tool_approval_org_external_request",
        "tool_approvals",
        ["organization_id", "external_request_id"],
    )

    op.add_column("tool_calls", sa.Column("approval_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tool_calls_approval_id", "tool_calls", "tool_approvals",
        ["approval_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_tool_calls_approval_id", "tool_calls", ["approval_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tool_calls_approval_id", table_name="tool_calls")
    op.drop_constraint("fk_tool_calls_approval_id", "tool_calls", type_="foreignkey")
    op.drop_column("tool_calls", "approval_id")
    op.drop_constraint(
        "uq_tool_approval_org_external_request", "tool_approvals", type_="unique"
    )
    op.drop_index("ix_tool_approvals_external_request_id", table_name="tool_approvals")
    op.drop_column("tool_approvals", "used_at")
    op.drop_column("tool_approvals", "target_url")
    op.drop_column("tool_approvals", "external_request_id")
