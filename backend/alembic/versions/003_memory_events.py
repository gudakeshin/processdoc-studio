"""memory events and project memory profiles"""

from alembic import op
import sqlalchemy as sa

revision = "003_memory_events"
down_revision = "002_run_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_events_project_id", "memory_events", ["project_id"])
    op.create_index("ix_memory_events_run_id", "memory_events", ["run_id"])
    op.create_index("ix_memory_events_created_at", "memory_events", ["created_at"])

    op.create_table(
        "project_memory_profiles",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_memory_profiles")
    op.drop_index("ix_memory_events_created_at", table_name="memory_events")
    op.drop_index("ix_memory_events_run_id", table_name="memory_events")
    op.drop_index("ix_memory_events_project_id", table_name="memory_events")
    op.drop_table("memory_events")
