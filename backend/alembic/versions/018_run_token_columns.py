"""add token tracking columns to runs table via Alembic

These columns were previously added by the _migrate_db() startup side-channel
in session.py.  This revision makes them part of the canonical alembic history
so that alembic upgrade head is sufficient and _migrate_db no longer diverges.

Revision ID: 018_run_token_columns
Revises: 017_membership_unique
Create Date: 2026-05-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018_run_token_columns"
down_revision = "017_membership_unique"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("tokens_input", sa.Integer),
    ("tokens_output", sa.Integer),
    ("tokens_cache_read", sa.Integer),
    ("tokens_cache_creation", sa.Integer),
    ("cost_usd", sa.Float),
]


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("runs")}
        for col_name, col_type in _COLUMNS:
            if col_name not in existing:
                batch_op.add_column(sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        for col_name, _col_type in _COLUMNS:
            batch_op.drop_column(col_name)
