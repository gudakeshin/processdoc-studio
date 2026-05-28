"""add unique constraint to memory_items (project_id, memory_type, key)

Revision ID: 016_memory_item_unique_key
Revises: 015_conversation_message_source_freshness
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op

revision = "016_memory_item_unique_key"
down_revision = "015_conversation_message_source_freshness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate rows, keeping the most recently updated entry per
    # (project_id, memory_type, key). The correlated subquery is compatible
    # with both SQLite and PostgreSQL.
    op.execute(
        """
        DELETE FROM memory_items WHERE id IN (
            SELECT m1.id FROM memory_items m1
            WHERE EXISTS (
                SELECT 1 FROM memory_items m2
                WHERE m2.project_id = m1.project_id
                  AND m2.memory_type = m1.memory_type
                  AND m2.key = m1.key
                  AND (m2.updated_at > m1.updated_at
                       OR (m2.updated_at = m1.updated_at AND m2.id < m1.id))
            )
        )
        """
    )
    with op.batch_alter_table("memory_items") as batch_op:
        batch_op.create_unique_constraint(
            "uq_memory_item_project_type_key",
            ["project_id", "memory_type", "key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("memory_items") as batch_op:
        batch_op.drop_constraint("uq_memory_item_project_type_key", type_="unique")
