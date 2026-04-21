"""add conversation message source freshness fields

Revision ID: 015_conversation_message_source_freshness
Revises: 014_project_brands
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015_conversation_message_source_freshness"
down_revision = "014_project_brands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column("source_type", sa.String(length=32), nullable=True))
    op.add_column("conversation_messages", sa.Column("source_freshness_at", sa.DateTime(), nullable=True))
    op.create_index("ix_conversation_messages_source_type", "conversation_messages", ["source_type"])
    op.create_index(
        "ix_conversation_messages_source_freshness_at",
        "conversation_messages",
        ["source_freshness_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_source_freshness_at", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_source_type", table_name="conversation_messages")
    op.drop_column("conversation_messages", "source_freshness_at")
    op.drop_column("conversation_messages", "source_type")
