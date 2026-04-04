"""add run control flags and hook executions

Revision ID: 010_run_controls_and_hook_execution
Revises: 009_memory_item_principal_id
Create Date: 2026-04-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "010_run_controls_and_hook_execution"
down_revision = "009_memory_item_principal_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("pause_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("runs", sa.Column("resume_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("runs", sa.Column("abort_requested", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "hook_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("hook_point", sa.String(length=64), nullable=False),
        sa.Column("hook_name", sa.String(length=128), nullable=False),
        sa.Column("hook_exec_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default="OK"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hook_exec_run_point_name", "hook_executions", ["run_id", "hook_point", "hook_name"])
    op.create_index("ix_hook_exec_idem", "hook_executions", ["run_id", "idempotency_key"])
    op.create_index("ix_hook_executions_run_id", "hook_executions", ["run_id"])
    op.create_index("ix_hook_executions_hook_exec_id", "hook_executions", ["hook_exec_id"])


def downgrade() -> None:
    op.drop_index("ix_hook_executions_hook_exec_id", table_name="hook_executions")
    op.drop_index("ix_hook_executions_run_id", table_name="hook_executions")
    op.drop_index("ix_hook_exec_idem", table_name="hook_executions")
    op.drop_index("ix_hook_exec_run_point_name", table_name="hook_executions")
    op.drop_table("hook_executions")

    op.drop_column("runs", "abort_requested")
    op.drop_column("runs", "resume_requested")
    op.drop_column("runs", "pause_requested")

