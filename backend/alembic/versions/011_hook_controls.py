"""add hook controls table

Revision ID: 011_hook_controls
Revises: 010_run_controls_hooks
Create Date: 2026-04-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "011_hook_controls"
down_revision = "010_run_controls_hooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hook_controls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("hook_name", sa.String(length=128), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hook_controls_project_hook", "hook_controls", ["project_id", "hook_name"])
    op.create_index("ix_hook_controls_hook_name", "hook_controls", ["hook_name"])
    op.create_index("ix_hook_controls_project_id", "hook_controls", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_hook_controls_project_id", table_name="hook_controls")
    op.drop_index("ix_hook_controls_hook_name", table_name="hook_controls")
    op.drop_index("ix_hook_controls_project_hook", table_name="hook_controls")
    op.drop_table("hook_controls")

