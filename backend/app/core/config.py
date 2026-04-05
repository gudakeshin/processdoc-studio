from __future__ import annotations

import os
from typing import Any, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment (see .env.example).

    Cowork-style run context: conversation_digest_* and coordinator_planning_context_chars feed the
    coordinator planner; subagent_conversation_digest_max_chars and subagent_narrative_thinking_enabled
    control worker prompts and optional narrative extended thinking.
    """

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    processdoc_env: str = "development"
    jwt_secret: str = "change-me"
    database_url: str = "sqlite:///./processdoc.db"
    # Applied to non-SQLite engines (e.g. Postgres). Size ≈ concurrent DB-bound requests per process.
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_pre_ping: bool = True
    # When False, Redis must be reachable or CacheService startup fails (avoids split-brain cache across API replicas).
    cache_allow_memory_fallback: bool = True
    workspace_root: str = "./workspace"
    redis_url: str = "redis://localhost:6379/0"

    jwt_algorithm: str = "HS256"
    jwt_access_exp_minutes: int = 60
    jwt_refresh_exp_days: int = 7
    jwt_sse_exp_seconds: int = 90

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    scheduler_enabled: bool = True
    auth_allow_self_signup: bool = False
    otel_sdk_enabled: bool = False

    anthropic_api_key: str = ""
    anthropic_claude_model: str = "claude-haiku-4-5"
    anthropic_temperature: float = 0.2
    anthropic_max_tokens: int = 4096
    # 0 = no aggregate cap per run (only per-request max_tokens apply).
    anthropic_max_tokens_per_run: int = 0
    coordinator_llm_planning_enabled: bool = True
    anthropic_thinking_budget_tokens: int = 8000
    anthropic_coordinator_plan_max_tokens: int = 8192
    # Cowork-style context: conversation digest + planner retrieval excerpt caps.
    conversation_digest_max_chars: int = 12000
    conversation_digest_message_limit: int = 45
    conversation_digest_planner_max_chars: int = 6000
    subagent_conversation_digest_max_chars: int = 3500
    coordinator_planning_context_chars: int = 7000
    # Optional extended thinking for narrative subagent (extra cost when enabled).
    subagent_narrative_thinking_enabled: bool = False
    anthropic_subagent_thinking_budget_tokens: int = 8000
    anthropic_timeout_sec: float = 45.0
    anthropic_circuit_breaker_failures: int = 5
    anthropic_circuit_breaker_reset_sec: int = 60
    subagent_tool_max_rounds: int = 5
    subagent_tool_max_tokens: int = 4096
    mcp_enabled: bool = False
    memory_events_retention_days: int = 30

    bash_tool_enabled: bool = False
    bash_tool_model: str = ""
    bash_session_timeout_sec: int = 3600
    bash_command_timeout_sec: int = 120
    bash_max_output_bytes: int = 65536
    bash_max_output_lines: int = 400
    bash_max_tool_rounds: int = 12
    bash_allowlist_enabled: bool = False
    bash_allowlist_commands: str = (
        "bash,sh,ls,cat,echo,pwd,head,tail,wc,grep,find,git,python,python3,pytest,node,npm"
    )
    bash_forbid_operators: bool = True
    bash_audit_log: Optional[str] = None
    bash_docker_enabled: bool = False
    bash_docker_image: str = "alpine:3.20"
    # Host path to seccomp JSON profile; empty disables --security-opt seccomp=...
    bash_docker_seccomp_profile: str = ""
    bash_rate_limit_per_minute: int = 20

    text_editor_tool_enabled: bool = False
    text_editor_tool_model: str = ""
    text_editor_max_characters: int = 12000
    text_editor_backup_enabled: bool = True
    text_editor_audit_log: Optional[str] = None
    text_editor_allowed_extensions: str = (
        ".py,.md,.txt,.json,.yaml,.yml,.toml,.ini,.cfg,.csv,.ts,.tsx,.js,.jsx,.html,.css,.sql,.xml,.env,.sh"
    )
    text_editor_max_file_bytes: int = 5242880

    run_queue_backend: str = "local"
    # When RUN_QUEUE_BACKEND=local, re-queue approved runs that show execution_enqueued but never
    # execution_started (e.g. API restart emptied the in-memory queue). Set false if you run multiple
    # API processes without Redis and cannot rely on the best-effort Redis NX startup lock.
    run_queue_startup_reconcile: bool = True
    # When RUN_QUEUE_BACKEND=redis, the API does not consume the queue unless you either run
    # `python -m app.workers.run_execution_worker` separately OR set this True (single-process / dev only).
    run_queue_embed_redis_consumer: bool = False
    run_execution_queue_name: str = "processdoc:run-execution"
    run_enqueue_dedupe_prefix: str = "processdoc:run-enqueue"
    run_enqueue_dedupe_ttl_sec: int = 3600
    run_dead_letter_index_key: str = "processdoc:run-dead-letter:index"
    run_dead_letter_item_prefix: str = "processdoc:run-dead-letter:item"
    run_worker_heartbeat_key_prefix: str = "processdoc:run-worker:heartbeat"
    run_events_channel_prefix: str = "processdoc:run-events"
    run_worker_heartbeat_ttl_sec: int = 20
    run_worker_id: str = Field(default_factory=lambda: f"worker-{os.getpid()}")
    run_max_active_global: int = 500
    run_max_active_per_project: int = 20
    run_max_active_per_user: int = 8
    run_dead_letter_max_replay_attempts: int = 3
    run_execution_retry_max_attempts: int = 3
    run_execution_retry_backoff_base_sec: float = 1.5
    run_execution_retry_backoff_max_sec: float = 20.0
    run_dead_letter_replay_cooldown_sec: int = 10
    format_negotiation_v2_enabled: bool = True
    instruction_decision_prompts_enabled: bool = True
    scratchpad_visibility_enabled: bool = True
    # Phase C: LLM strategy options + execution_strategy decision prompt (extra Anthropic call per plan message).
    strategy_options_planning_enabled: bool = False

    # Swarm orchestration: DAG-backed run_tasks, team/teammate rows, messaging API, enriched todo snapshots.
    swarm_orchestration_enabled: bool = False
    # When True and Claude is enabled, lead may extend the task graph via LLM (future hook).
    swarm_llm_lead_enabled: bool = False
    # When True and project workspace is a git repo, create git worktrees for teammate dirs (best-effort).
    swarm_git_worktrees_enabled: bool = False
    # When True, coordinator runs queued RunTask rows with phase=custom after main outputs.
    swarm_execute_custom_tasks_enabled: bool = False

    # Phase 0: Agentic loop - event-driven coordinator using CoordinatorStateManager (opt-in, defaults to False for backward compat).
    # When True, coordinator uses state machine loop instead of linear ThreadPoolExecutor execution.
    coordinator_agentic_loop_enabled: bool = False
    # When True and coordinator_agentic_loop_enabled, use subprocess-based teammate execution (Phase 2 feature).
    subprocess_execution_enabled: bool = False

    memory_v2_retrieval_enabled: bool = True
    # When True, coordinator uses assemble_v2 so MemoryItem, MemoryEvent, and ProjectMemoryProfile feed assembled_context.
    memory_compaction_v1_enabled: bool = True
    memory_compaction_char_cap: int = 32000
    # Block MemoryItem rows with consent_state != allowed from context and memory_items tool (DPDP-aware).
    memory_respect_consent_in_context: bool = True
    # When True, MemoryItem rows with principal_id set require a matching Consent Ledger grant (latest row).
    memory_enforce_consent_ledger: bool = False
    # Allow POST /api/memory/{pid}/batch for multi-item HITL-confirmed adds (e.g. from chat).
    memory_batch_create_enabled: bool = True
    processdoc_coordinator_debug_log: str = ""

    processdoc_runs_debug_log: str = ""
    observability_snapshot_path: str = ""
    structured_logging_enabled: bool = False

    model_realtime_redis_channel_prefix: str = "processdoc:model-events"
    drawio_collab_channel_prefix: str = "processdoc:drawio-collab"
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    brave_search_api_key: str = ""
    google_custom_search_api_key: str = ""
    google_custom_search_cx: str = ""
    lp_library_local_path: str = ""
    policy_evaluator_version: str = "policy-v1"
    policy_classifier_threshold: float = 0.5
    policy_enforce_enabled: bool = True
    policy_bundle_path: str = ""
    event_contract_strict: bool = True
    retry_cooldown_threshold_sec: float = 20.0
    run_retry_indefinite_for_scheduled: bool = False

    # Deliverable quality contracts (config/quality_contracts/*.json) + registry-driven critique/revise loops.
    quality_contracts_dir: str = ""
    deliverable_quality_enabled: bool = True
    deliverable_quality_max_revision_rounds: int = 2

    upload_max_bytes: int = 50 * 1024 * 1024

    @field_validator(
        "bash_tool_enabled",
        "bash_allowlist_enabled",
        "bash_forbid_operators",
        "bash_docker_enabled",
        "text_editor_tool_enabled",
        "text_editor_backup_enabled",
        "scheduler_enabled",
        "auth_allow_self_signup",
        "format_negotiation_v2_enabled",
        "instruction_decision_prompts_enabled",
        "scratchpad_visibility_enabled",
        "strategy_options_planning_enabled",
        "memory_v2_retrieval_enabled",
        "memory_compaction_v1_enabled",
        "memory_respect_consent_in_context",
        "memory_enforce_consent_ledger",
        "memory_batch_create_enabled",
        "coordinator_llm_planning_enabled",
        "mcp_enabled",
        "database_pool_pre_ping",
        "cache_allow_memory_fallback",
        "langfuse_enabled",
        "deliverable_quality_enabled",
        "structured_logging_enabled",
        "run_queue_embed_redis_consumer",
        "run_queue_startup_reconcile",
        "swarm_git_worktrees_enabled",
        "swarm_execute_custom_tasks_enabled",
        "subagent_narrative_thinking_enabled",
        mode="before",
    )
    @classmethod
    def _coerce_bool_flag(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        s = str(v).strip().lower()
        if s in {"1", "true", "yes"}:
            return True
        if s in {"0", "false", "no", ""}:
            return False
        return bool(v)

    @field_validator("bash_audit_log", "text_editor_audit_log", mode="before")
    @classmethod
    def _empty_audit_log_none(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return str(v).strip() if v else None

    @field_validator("run_queue_backend", mode="before")
    @classmethod
    def _normalize_queue_backend(cls, v: Any) -> str:
        return str(v or "local").strip().lower()

    @model_validator(mode="after")
    def _validate_secrets_and_urls(self) -> Settings:
        env_name = (self.processdoc_env or "development").strip().lower()
        if env_name in ("production", "prod", "staging"):
            bad = ("change-me", "", "changeme")
            secret = self.jwt_secret.strip().lower()
            if secret in bad or len(self.jwt_secret.strip()) < 16:
                raise ValueError(
                    "JWT_SECRET must be a strong secret (min 16 chars, not 'change-me') "
                    f"when PROCESSDOC_ENV is {self.processdoc_env!r}"
                )
        if not (self.database_url or "").strip():
            raise ValueError("DATABASE_URL must not be empty")
        if self.run_queue_backend not in {"local", "redis"}:
            raise ValueError("RUN_QUEUE_BACKEND must be 'local' or 'redis'")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_allow_origin_regex(self) -> str | None:
        """In non-production, allow common dev Origins (any port) so fetch works from LAN IPs, not only CORS_ORIGINS."""
        env_name = (self.processdoc_env or "development").strip().lower()
        if env_name in ("production", "prod", "staging"):
            return None
        # localhost / loopback / typical RFC1918 LAN (browser Origin when using http://IP:3000 etc.)
        return (
            r"https?://("
            r"localhost|127\.0\.0\.1|\[::1\]|"
            r"192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}"
            r")(:\d+)?$"
        )


settings = Settings()


def log_memory_config_warnings() -> None:
    """Log non-fatal configuration combinations that affect project memory in context."""
    import logging

    log = logging.getLogger("processdoc.config")
    if settings.memory_compaction_v1_enabled and not settings.memory_v2_retrieval_enabled:
        log.warning(
            "MEMORY_COMPACTION_V1_ENABLED is true but MEMORY_V2_RETRIEVAL_ENABLED is false: "
            "MemoryItem rows from the Memory page are not merged into assembled_context; "
            "memory events and project profile still apply."
        )


def describe_database_url_for_logs(url: str) -> str:
    """Database URL summary for logs (no credentials)."""
    u = (url or "").strip()
    if not u:
        return "(empty)"
    if u.startswith("sqlite"):
        return u.split("?", 1)[0]
    try:
        from urllib.parse import urlparse

        p = urlparse(u)
        host = p.hostname or ""
        port = f":{p.port}" if p.port else ""
        db = (p.path or "").lstrip("/") or "(default)"
        return f"{p.scheme}://{host}{port}/{db}"
    except Exception:
        return "(unparseable)"


def log_run_queue_startup_config(*, repo_env_present: bool, backend_env_present: bool) -> None:
    """Log effective queue backend and DB URL shape so misconfigured .env is obvious in logs."""
    import logging

    log = logging.getLogger("processdoc.config")
    log.info(
        "Run queue startup: RUN_QUEUE_BACKEND=%s DATABASE_URL=%s dotenv(repo_root)=%s dotenv(backend)=%s",
        settings.run_queue_backend,
        describe_database_url_for_logs(settings.database_url),
        repo_env_present,
        backend_env_present,
    )
    placeholder_markers = ("user:password", "@USER:", "USER:PASSWORD")
    du = settings.database_url.lower()
    if any(m in du for m in placeholder_markers):
        log.warning(
            "DATABASE_URL looks like a placeholder; the API will fail to connect. "
            "Use sqlite:///./processdoc.db for local dev or postgres credentials matching docker-compose."
        )


def bash_allowlist_set() -> frozenset[str]:
    parts = {p.strip().lower() for p in settings.bash_allowlist_commands.split(",") if p.strip()}
    return frozenset(parts)


def text_editor_allowed_extensions_set() -> frozenset[str]:
    parts = {p.strip().lower() for p in settings.text_editor_allowed_extensions.split(",") if p.strip()}
    normalized = {(p if p.startswith(".") else f".{p}") for p in parts}
    return frozenset(normalized)
