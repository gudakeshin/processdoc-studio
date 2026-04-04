"""user project preferences for personalization context"""

from alembic import op
import sqlalchemy as sa

revision = "008_user_project_preferences"
down_revision = "007_add_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_project_preferences",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("preferences_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )


def downgrade() -> None:
    op.drop_table("user_project_preferences")
