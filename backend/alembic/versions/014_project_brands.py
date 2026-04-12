"""project branding table

Revision ID: 014_project_brands
Revises: 013_swarm_orchestration
Create Date: 2026-04-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014_project_brands"
down_revision = "013_swarm_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_brands",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("primary_color", sa.String(length=16), nullable=True),
        sa.Column("font_family", sa.String(length=64), nullable=True),
        sa.Column("font_size_base", sa.Integer(), nullable=True),
        sa.Column("logo_url", sa.String(length=1024), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("footer_text", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_project_brands_project_id", "project_brands", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_brands_project_id", table_name="project_brands")
    op.drop_table("project_brands")

