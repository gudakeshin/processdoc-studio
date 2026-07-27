"""add unique constraint to memberships(project_id, user_id)

Deduplicates existing rows by keeping the highest-privilege role per
(project_id, user_id) pair (Owner > Editor > Viewer), then creates the
unique constraint so duplicates cannot be inserted in future.

Revision ID: 017_membership_unique
Revises: 016_memory_item_unique_key
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op

revision = "017_membership_unique"
down_revision = "016_memory_item_unique_key"
branch_labels = None
depends_on = None

# Priority mapping: lower number = keep this row (higher privilege)
_ROLE_PRIORITY = """
CASE role
    WHEN 'Owner'  THEN 1
    WHEN 'Editor' THEN 2
    WHEN 'Viewer' THEN 3
    ELSE 4
END
"""


def upgrade() -> None:
    # Remove duplicate (project_id, user_id) rows, keeping highest-privilege role.
    # For ties in role priority, keep the row with the lexicographically smallest id
    # (arbitrary-but-deterministic tiebreak since membership ids are random strings).
    op.execute(
        f"""
        DELETE FROM memberships WHERE id IN (
            SELECT m1.id FROM memberships m1
            WHERE EXISTS (
                SELECT 1 FROM memberships m2
                WHERE m2.project_id = m1.project_id
                  AND m2.user_id    = m1.user_id
                  AND (
                      {_ROLE_PRIORITY.replace("role", "m2.role")} < {_ROLE_PRIORITY.replace("role", "m1.role")}
                      OR (
                          {_ROLE_PRIORITY.replace("role", "m2.role")} = {_ROLE_PRIORITY.replace("role", "m1.role")}
                          AND m2.id < m1.id
                      )
                  )
            )
        )
        """
    )
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.create_unique_constraint(
            "uq_memberships_project_user",
            ["project_id", "user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("uq_memberships_project_user", type_="unique")
