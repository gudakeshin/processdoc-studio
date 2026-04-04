"""Optional principal_id on memory_items for DPDP Consent Ledger linkage."""

from alembic import op
import sqlalchemy as sa

revision = "009_memory_item_principal_id"
down_revision = "008_user_project_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_items",
        sa.Column("principal_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_memory_items_principal_id", "memory_items", ["principal_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_items_principal_id", table_name="memory_items")
    op.drop_column("memory_items", "principal_id")
