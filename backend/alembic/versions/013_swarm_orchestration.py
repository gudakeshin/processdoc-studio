"""swarm teams, messages, run_task swarm columns

Revision ID: 013_swarm_orchestration
Revises: 012_refresh_tokens
Create Date: 2026-04-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "013_swarm_orchestration"
down_revision = "012_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "swarm_teams",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_swarm_teams_run_id", "swarm_teams", ["run_id"])

    op.create_table(
        "swarm_teammates",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("team_id", sa.String(length=64), sa.ForeignKey("swarm_teams.id"), nullable=False),
        sa.Column("teammate_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="worker"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_swarm_teammates_team", "swarm_teammates", ["team_id"])

    op.create_table(
        "swarm_messages",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("team_id", sa.String(length=64), sa.ForeignKey("swarm_teams.id"), nullable=True),
        sa.Column("from_teammate", sa.String(length=64), nullable=False),
        sa.Column("to_teammate", sa.String(length=64), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_swarm_messages_run_created", "swarm_messages", ["run_id", "created_at"])

    # run_tasks historically existed only via SQLAlchemy create_all (SQLite). Fresh
    # Postgres migrations never created it — create the full table here when missing.
    bind = op.get_bind()
    inspector = inspect(bind)
    if "run_tasks" not in inspector.get_table_names():
        op.create_table(
            "run_tasks",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("run_id", sa.String(length=64), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("phase", sa.String(length=16), nullable=False, server_default="act"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("depends_on_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("swarm_team_id", sa.String(length=64), sa.ForeignKey("swarm_teams.id"), nullable=True),
            sa.Column("assigned_teammate_id", sa.String(length=64), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skills_used_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("tools_invoked_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("output_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("blocked_reason", sa.Text(), nullable=True),
            sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_duration_sec", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_run_tasks_run_id", "run_tasks", ["run_id"])
        op.create_index("ix_run_tasks_project_id", "run_tasks", ["project_id"])
        op.create_index("ix_run_tasks_run_phase", "run_tasks", ["run_id", "phase"])
        op.create_index("ix_run_tasks_run_status", "run_tasks", ["run_id", "status"])
    else:
        cols = {c["name"] for c in inspector.get_columns("run_tasks")}
        if "swarm_team_id" not in cols:
            op.add_column("run_tasks", sa.Column("swarm_team_id", sa.String(length=64), nullable=True))
        if "assigned_teammate_id" not in cols:
            op.add_column("run_tasks", sa.Column("assigned_teammate_id", sa.String(length=64), nullable=True))
        if "priority" not in cols:
            op.add_column(
                "run_tasks",
                sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            )
        fks = {fk["name"] for fk in inspector.get_foreign_keys("run_tasks")}
        if "fk_run_tasks_swarm_team_id" not in fks:
            op.create_foreign_key(
                "fk_run_tasks_swarm_team_id",
                "run_tasks",
                "swarm_teams",
                ["swarm_team_id"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "run_tasks" in inspector.get_table_names():
        fks = {fk["name"] for fk in inspector.get_foreign_keys("run_tasks")}
        if "fk_run_tasks_swarm_team_id" in fks:
            op.drop_constraint("fk_run_tasks_swarm_team_id", "run_tasks", type_="foreignkey")
        cols = {c["name"] for c in inspector.get_columns("run_tasks")}
        for col in ("priority", "assigned_teammate_id", "swarm_team_id"):
            if col in cols:
                op.drop_column("run_tasks", col)

    op.drop_index("ix_swarm_messages_run_created", table_name="swarm_messages")
    op.drop_table("swarm_messages")

    op.drop_index("ix_swarm_teammates_team", table_name="swarm_teammates")
    op.drop_table("swarm_teammates")

    op.drop_index("ix_swarm_teams_run_id", table_name="swarm_teams")
    op.drop_table("swarm_teams")
