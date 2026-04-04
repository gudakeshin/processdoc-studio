"""add query indexes for run and consent lookups"""

from alembic import op

revision = "007_add_query_indexes"
down_revision = "006_memory_items_and_scheduled_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_runs_project_id", "runs", ["project_id"], unique=False)
    op.create_index("ix_runs_created_at", "runs", ["created_at"], unique=False)
    op.create_index("ix_runs_project_created_at", "runs", ["project_id", "created_at"], unique=False)
    op.create_index("ix_memberships_project_user", "memberships", ["project_id", "user_id"], unique=False)
    op.create_index("ix_consent_ledger_project_id", "consent_ledger", ["project_id"], unique=False)
    op.create_index("ix_consent_ledger_principal_id", "consent_ledger", ["principal_id"], unique=False)
    op.create_index(
        "ix_consent_ledger_project_principal",
        "consent_ledger",
        ["project_id", "principal_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_consent_ledger_project_principal", table_name="consent_ledger")
    op.drop_index("ix_consent_ledger_principal_id", table_name="consent_ledger")
    op.drop_index("ix_consent_ledger_project_id", table_name="consent_ledger")
    op.drop_index("ix_memberships_project_user", table_name="memberships")
    op.drop_index("ix_runs_project_created_at", table_name="runs")
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_index("ix_runs_project_id", table_name="runs")
