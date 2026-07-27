"""memory items and scheduled tasks"""

from alembic import op
import sqlalchemy as sa

revision = "006_memory_items_tasks"
down_revision = "005_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("consent_state", sa.String(length=16), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_items_project_id", "memory_items", ["project_id"])
    op.create_index("ix_memory_items_memory_type", "memory_items", ["memory_type"])
    op.create_index("ix_memory_items_created_at", "memory_items", ["created_at"])

    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("output_types_json", sa.Text(), nullable=False),
        sa.Column("custom_output_formats_json", sa.Text(), nullable=False),
        sa.Column("output_format_preferences_json", sa.Text(), nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("retry_limit", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_tasks_project_id", "scheduled_tasks", ["project_id"])
    op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"])

    op.create_table(
        "scheduled_task_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["scheduled_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_task_runs_task_id", "scheduled_task_runs", ["task_id"])
    op.create_index("ix_scheduled_task_runs_project_id", "scheduled_task_runs", ["project_id"])
    op.create_index("ix_scheduled_task_runs_created_at", "scheduled_task_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_task_runs_created_at", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_project_id", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_task_id", table_name="scheduled_task_runs")
    op.drop_table("scheduled_task_runs")

    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_project_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")

    op.drop_index("ix_memory_items_created_at", table_name="memory_items")
    op.drop_index("ix_memory_items_memory_type", table_name="memory_items")
    op.drop_index("ix_memory_items_project_id", table_name="memory_items")
    op.drop_table("memory_items")
