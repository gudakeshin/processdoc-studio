from datetime import datetime, timezone
import json

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class RefreshToken(Base):
    """Server-tracked refresh JWTs (jti rotation + revocation)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ProjectBrand(Base):
    __tablename__ = "project_brands"
    __table_args__ = (Index("ix_project_brands_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False)
    primary_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    font_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    font_size_base: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    footer_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        Index("ix_memberships_project_user", "project_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_project_created_at", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    output_types: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    plan_payload: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pause_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resume_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    abort_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SwarmTeam(Base):
    """Logical agent team for a run (swarm orchestration)."""

    __tablename__ = "swarm_teams"
    __table_args__ = (Index("ix_swarm_teams_run_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SwarmTeammate(Base):
    __tablename__ = "swarm_teammates"
    __table_args__ = (Index("ix_swarm_teammates_team", "team_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(64), ForeignKey("swarm_teams.id"), nullable=False)
    teammate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="worker")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class SwarmMessage(Base):
    __tablename__ = "swarm_messages"
    __table_args__ = (
        Index("ix_swarm_messages_run_created", "run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False)
    team_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("swarm_teams.id"), nullable=True)
    from_teammate: Mapped[str] = mapped_column(String(64), nullable=False)
    to_teammate: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    @property
    def payload_json(self) -> dict:
        try:
            obj = json.loads(self.payload)
            return obj if isinstance(obj, dict) else {"value": obj}
        except Exception:
            return {"value": self.payload}


class RunTask(Base):
    __tablename__ = "run_tasks"
    __table_args__ = (
        Index("ix_run_tasks_run_phase", "run_id", "phase"),
        Index("ix_run_tasks_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase: Mapped[str] = mapped_column(String(16), nullable=False, default="act")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depends_on_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    swarm_team_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("swarm_teams.id"), nullable=True)
    assigned_teammate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skills_used_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    tools_invoked_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class HookExecution(Base):
    __tablename__ = "hook_executions"
    __table_args__ = (
        Index("ix_hook_exec_run_point_name", "run_id", "hook_point", "hook_name"),
        Index("ix_hook_exec_idem", "run_id", "idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False, index=True)
    hook_point: Mapped[str] = mapped_column(String(64), nullable=False)
    hook_name: Mapped[str] = mapped_column(String(128), nullable=False)
    hook_exec_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="OK")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class HookControl(Base):
    __tablename__ = "hook_controls"
    __table_args__ = (
        Index("ix_hook_controls_project_hook", "project_id", "hook_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    hook_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ConsentLedger(Base):
    __tablename__ = "consent_ledger"
    __table_args__ = (
        Index("ix_consent_ledger_project_principal", "project_id", "principal_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    granted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class DPDPRightsRequest(Base):
    __tablename__ = "dpdp_rights_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)  # access|correction|erasure
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MemoryEvent(Base):
    __tablename__ = "memory_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ProjectMemoryProfile(Base):
    __tablename__ = "project_memory_profiles"

    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), primary_key=True)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class UserProjectPreference(Base):
    """Per-user, per-project personalization (v4 §5.1): context_lines merged into assembled context."""

    __tablename__ = "user_project_preferences"

    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), primary_key=True)
    preferences_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Creative Studio")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # preference|constraint|decision|fact
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="chat")
    consent_state: Mapped[str] = mapped_column(String(16), nullable=False, default="allowed")
    # When set, optional DPDP Consent Ledger check for this principal (see memory_enforce_consent_ledger).
    principal_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    output_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Keep legacy DB column names for compatibility; expose output-type semantics in code.
    custom_output_types_json: Mapped[str] = mapped_column("custom_output_formats_json", Text, nullable=False, default="[]")
    output_type_representations_json: Mapped[str] = mapped_column("output_format_preferences_json", Text, nullable=False, default="{}")
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False, default="interval")  # interval|once
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|paused|archived
    retry_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ScheduledTaskRun(Base):
    __tablename__ = "scheduled_task_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("scheduled_tasks.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class WikiPage(Base):
    """Persistent wiki pages (LLM-maintained, markdown format)."""

    __tablename__ = "wiki_pages"
    __table_args__ = (
        Index("ix_wiki_pages_wiki_type_project", "wiki_type", "project_id"),
        Index("ix_wiki_pages_project_slug", "project_id", "slug"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wiki_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # "leading_practice" or "project"
    project_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("projects.id"), nullable=True, index=True)  # None for LP wiki
    page_name: Mapped[str] = mapped_column(String(255), nullable=False)  # File name without .md
    slug: Mapped[str] = mapped_column(String(255), nullable=False)  # URL-friendly identifier
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # entity|concept|comparison|template|synthesis|artifact
    content: Mapped[str] = mapped_column(Text, nullable=False)  # Markdown body
    frontmatter: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # YAML metadata as JSON
    inbound_links: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list of page IDs
    outbound_links: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list of page IDs
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "system" for auto-generated
    source_memory_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    source_run_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")  # low|medium|high
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class WikiLog(Base):
    """Append-only log of wiki operations (ingest, query, lint, update)."""

    __tablename__ = "wiki_logs"
    __table_args__ = (
        Index("ix_wiki_logs_wiki_type_project_ts", "wiki_type", "project_id", "timestamp"),
        Index("ix_wiki_logs_operation_ts", "operation", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wiki_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("projects.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # ingest|query|lint|update
    source_name: Mapped[str | None] = mapped_column(String(512), nullable=True)  # e.g., article title, run_id, URL
    pages_touched: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list of page IDs
    corrections_made: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list of corrections
    qa_results: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: {passed, issues, suggestions}
    executed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "system" or user_id
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class WikiIndex(Base):
    """Catalog index of all wiki pages (updated on each ingest)."""

    __tablename__ = "wiki_indexes"
    __table_args__ = (
        Index("ix_wiki_indexes_wiki_type_project", "wiki_type", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wiki_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("projects.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # Markdown: catalog of all pages by category
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_counts: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON: {entity: N, concept: M, ...}
