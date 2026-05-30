"""add composite indexes on runs table for admission control queries

Revision ID: 019_run_admission_index
Revises: 018_run_token_columns
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op


revision = "019_run_admission_index"
down_revision = "018_run_token_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_runs_project_status", "runs", ["project_id", "status"])
    op.create_index("ix_runs_approved_by_status", "runs", ["approved_by", "status"])
    op.create_index("ix_runs_status", "runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_approved_by_status", table_name="runs")
    op.drop_index("ix_runs_project_status", table_name="runs")
