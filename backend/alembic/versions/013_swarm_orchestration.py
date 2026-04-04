"""swarm teams, messages, run_task swarm columns

Revision ID: 013_swarm_orchestration
Revises: 012_refresh_tokens
Create Date: 2026-04-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

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

    op.add_column("run_tasks", sa.Column("swarm_team_id", sa.String(length=64), nullable=True))
    op.add_column("run_tasks", sa.Column("assigned_teammate_id", sa.String(length=64), nullable=True))
    op.add_column("run_tasks", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.create_foreign_key(
        "fk_run_tasks_swarm_team_id",
        "run_tasks",
        "swarm_teams",
        ["swarm_team_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_run_tasks_swarm_team_id", "run_tasks", type_="foreignkey")
    op.drop_column("run_tasks", "priority")
    op.drop_column("run_tasks", "assigned_teammate_id")
    op.drop_column("run_tasks", "swarm_team_id")

    op.drop_index("ix_swarm_messages_run_created", table_name="swarm_messages")
    op.drop_table("swarm_messages")

    op.drop_index("ix_swarm_teammates_team", table_name="swarm_teammates")
    op.drop_table("swarm_teammates")

    op.drop_index("ix_swarm_teams_run_id", table_name="swarm_teams")
    op.drop_table("swarm_teams")
