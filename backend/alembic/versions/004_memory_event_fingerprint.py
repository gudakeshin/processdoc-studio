"""memory event fingerprint dedupe"""

from alembic import op
import sqlalchemy as sa

revision = "004_memory_event_fingerprint"
down_revision = "003_memory_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_events", sa.Column("fingerprint", sa.String(length=64), nullable=True))
    op.execute("UPDATE memory_events SET fingerprint = 'legacy' WHERE fingerprint IS NULL")
    op.alter_column("memory_events", "fingerprint", nullable=False)
    op.create_index(
        "ix_memory_events_project_run_type_fingerprint",
        "memory_events",
        ["project_id", "run_id", "event_type", "fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_memory_events_project_run_type_fingerprint", table_name="memory_events")
    op.drop_column("memory_events", "fingerprint")
