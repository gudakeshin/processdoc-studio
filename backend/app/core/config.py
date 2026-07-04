from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _get_env_files() -> list[str]:
    """Calculate .env file paths relative to this config.py file."""
    config_file = Path(__file__)
    backend_dir = config_file.parent.parent.parent  # up 3 levels to backend/
    repo_root = backend_dir.parent  # up 1 more level to repo root

    env_files = [
        str(repo_root / ".env"),  # Load repo root .env first
        str(backend_dir / ".env"),  # Then backend .env (overrides repo root)
    ]

    for ef in env_files:
        logger.info("[CONFIG] env file %s (exists=%s)", ef, Path(ef).exists())

    return env_files


class Settings(BaseSettings):
    """Application settings loaded from environment (see .env.example).

    Cowork-style run context: conversation_digest_* and coordinator_planning_context_chars feed the
    coordinator planner; subagent_conversation_digest_max_chars and subagent_narrative_thinking_enabled
    control worker prompts and optional narrative extended thinking.
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_file=_get_env_files(),
    )

    processdoc_env: str = "development"
    jwt_secret: str = ""
    database_url: str = "sqlite:///./processdoc.db"
    # Applied to non-SQLite engines (e.g. Postgres). Size ≈ concurrent DB-bound requests per process.
    # Raise well above default for 500+ concurrent users; each SSE stream holds a connection.
    database_pool_size: int = 20
    database_max_overflow: int = 20
    database_pool_pre_ping: bool = True
    # Recycle connections after this many seconds to avoid stale connections behind load balancers.
    database_pool_recycle: int = 300
    # Seconds to wait for a free pool connection before raising; prevents silent hangs.
    database_pool_timeout: int = 30
    # When False, Redis must be reachable or CacheService startup fails (avoids split-brain cache across API replicas).
    cache_allow_memory_fallback: bool = True
    workspace_root: str = "./workspace"
    redis_url: str = "redis://localhost:6379/0"
    # Shared connection pool for SSE pub/sub. Each active SSE stream borrows one
    # pubsub connection; size to >= peak concurrent streams expected.
    sse_redis_max_connections: int = 300

    # SMTP for outbound email (financial report delivery). Email is disabled when
    # smtp_host is empty — send_email() returns {"sent": False, "reason": "email_not_configured"}.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    jwt_algorithm: str = "HS256"
    jwt_access_exp_minutes: int = 60
    jwt_refresh_exp_days: int = 7
    jwt_sse_exp_seconds: int = 90

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # SlowAPI limit strings, e.g. "30/minute" (see limits.readthedocs.io).
    auth_login_rate_limit: str = "30/minute"
    auth_refresh_rate_limit: str = "60/minute"
    # Per-IP rate limits for high-cost run operations (LLM calls, execution triggers).
    run_create_rate_limit: str = "20/minute"
    run_approve_rate_limit: str = "20/minute"
    run_recommend_rate_limit: str = "30/minute"
    run_regenerate_rate_limit: str = "10/minute"
    # Per-IP rate limits for scipy-heavy model calculation endpoints.
    model_calc_rate_limit: str = "30/minute"   # NPV, IRR, metrics
    model_dcf_rate_limit: str = "10/minute"    # DCF, sensitivity
    model_forecast_rate_limit: str = "20/minute"  # all 6 forecast methods
    scheduler_enabled: bool = True
    auth_allow_self_signup: bool = False
    # Comma-separated emails permitted to mutate the shared leading_practice wiki.
    # Empty in development = any authenticated user (matches historical behavior);
    # in staging/production, an empty list blocks all LP mutations.
    wiki_lp_admin_emails: str = ""
    wiki_meta_schema_versioning_enabled: bool = True
    wiki_evented_graph_rebuild_enabled: bool = False
    wiki_evented_graph_rebuild_fallback_sync_enabled: bool = True
    wiki_health_scorecard_enabled: bool = True
    wiki_storyline_canvas_enabled: bool = False

    # Intent-triggered pre-search: when the coordinator detects search-like phrasing
    # in the user's instruction, it runs wiki + web searches before context assembly.
    # Disable either leg to cap cost, latency, or outbound-network usage.
    coordinator_pre_search_enabled: bool = True
    coordinator_pre_search_web_enabled: bool = True

    # Trust X-Forwarded-For / X-Forwarded-Proto from upstream proxies (ALB, nginx, Cloudflare).
    # When enabled, SlowAPI rate limits key off the real client IP instead of the proxy IP.
    # trust_forwarded_for_hosts is a comma-separated list; "*" trusts any upstream.
    trust_forwarded_for_enabled: bool = False
    trust_forwarded_for_hosts: str = "127.0.0.1"

    otel_sdk_enabled: bool = False

    anthropic_api_key: str = ""
    anthropic_claude_model: str = "claude-haiku-4-5"
    anthropic_temperature: float = 0.2
    anthropic_max_tokens: int = 4096
    # Per-run token budget: set to 0 to disable (was 0 = disabled, now 50000 = ~$2-3 worth)
    anthropic_max_tokens_per_run: int = 50000
    coordinator_llm_planning_enabled: bool = True
    anthropic_thinking_budget_tokens: int = 8000
    anthropic_coordinator_plan_max_tokens: int = 8192
    # Anthropic pricing ($/MTok) — update when rates change or override via env
    llm_price_input_per_mtok: float = 3.00
    llm_price_output_per_mtok: float = 15.00
    llm_price_cache_read_per_mtok: float = 0.30
    llm_price_cache_creation_per_mtok: float = 3.75
    # Token budget & compression settings
    token_estimate_ratio: float = 3.5  # empirical: chars per token
    token_budget_safety_margin_tokens: int = 500  # reserve tokens for estimation errors
    prompt_compression_enabled: bool = True
    prompt_compression_strategy: str = "aggressive"  # "conservative" or "aggressive"
    prompt_compression_log_verbose: bool = True
    # Per-call budget limits (in tokens)
    subagent_max_prompt_tokens: int = 6000  # max prompt tokens for subagent calls
    coordinator_max_prompt_tokens: int = 12000  # max prompt tokens for coordinator planning
    proposal_max_prompt_tokens: int = 8000  # max prompt tokens for proposal generation
    # Cowork-style context: conversation digest + planner retrieval excerpt caps.
    conversation_digest_max_chars: int = 12000
    conversation_digest_message_limit: int = 45
    conversation_digest_planner_max_chars: int = 6000
    conversation_digest_tiered_compaction_enabled: bool = False
    conversation_digest_tiered_compaction_threshold_chars: int = 32000
    conversation_digest_sectioned_assembly_enabled: bool = False
    conversation_source_freshness_ttl_seconds: int = 259200
    conversation_digest_exclude_stale_sources: bool = True
    subagent_conversation_digest_max_chars: int = 3500
    coordinator_planning_context_chars: int = 7000
    # Optional extended thinking for narrative subagent (extra cost when enabled).
    subagent_narrative_thinking_enabled: bool = False
    anthropic_subagent_thinking_budget_tokens: int = 8000

    # Tiered model routing (Deloitte-quality program, Pillar A).
    # Stronger models author the narrative spine and critique the output; the
    # haiku default (anthropic_claude_model) still drafts the bulk slide/section copy.
    model_tiering_enabled: bool = True
    anthropic_planning_model: str = "claude-opus-4-8"
    anthropic_critique_model: str = "claude-sonnet-4-6"
    anthropic_planning_thinking_budget_tokens: int = 6000
    # Storyline contract: a slide-by-slide narrative spine authored before rendering
    # and enforced downstream. Set False to fall back to ad-hoc generation.
    storyline_contract_enabled: bool = True
    # Embed grounded figures (value chain, risk heat map, roadmap) in DOCX output.
    docx_figures_enabled: bool = True
    # DOCX consumes the same storyline contract as PPTX (no-op when
    # storyline_contract_enabled is False).
    docx_storyline_spine_enabled: bool = True
    # In-process bounded critique→revise loop: design-review/action-title hints drive
    # ONE targeted per-slide (PPTX) / per-section (DOCX) rewrite before render.
    deliverable_critique_loop_enabled: bool = True
    # Evidence soft-block: unsupported numeric claims trigger ONE targeted rewrite
    # (add caveat or drop the number); render always proceeds afterwards.
    evidence_soft_block_enabled: bool = True
    # Phase 2: pre-render layout planner (demote dense cards, split long lists/tables,
    # move overflow prose to speaker notes). Disabled → current trim-at-render behavior.
    pptx_layout_planner_enabled: bool = False
    # Phase 3: waterfall / gantt / harvey balls / benchmark bar figures.
    figure_vocab_v2_enabled: bool = False
    # Phase 4: DOCX page header, multilevel heading numbers, cross-refs, pull quotes.
    docx_formatting_v2_enabled: bool = False
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
    bash_audit_log: str | None = None
    bash_docker_enabled: bool = False
    bash_docker_image: str = "alpine:3.20"
    # Host path to seccomp JSON profile; empty disables --security-opt seccomp=...
    bash_docker_seccomp_profile: str = ""
    bash_rate_limit_per_minute: int = 20

    text_editor_tool_enabled: bool = False
    text_editor_tool_model: str = ""
    text_editor_max_characters: int = 12000
    text_editor_backup_enabled: bool = True
    text_editor_audit_log: str | None = None
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
    # Parallel workers for the local (non-Redis) queue. Each worker is a thread executing one run.
    # At 500 users, use RUN_QUEUE_BACKEND=redis with external worker processes instead.
    run_queue_local_max_workers: int = 4
    # A run in status="running" that emits no RunEvent for this many seconds is considered hung:
    # the coordinator deadline aborts it mid-stream and the stuck-run watchdog auto-fails it,
    # freeing the admission slot. Set 0 to disable both (no wall-clock timeout).
    run_stuck_timeout_sec: int = 600
    # On SIGTERM/SIGINT (docker stop, rolling deploy), the local dispatch loop stops
    # pulling new jobs and waits up to this long for in-flight runs to finish before
    # the process exits. See app.services.run_worker.drain_execution_worker.
    run_drain_timeout_sec: float = 30.0
    run_dead_letter_max_replay_attempts: int = 3
    run_execution_retry_max_attempts: int = 3
    run_execution_retry_backoff_base_sec: float = 1.5
    run_execution_retry_backoff_max_sec: float = 20.0
    run_dead_letter_replay_cooldown_sec: int = 10
    format_negotiation_v2_enabled: bool = True
    instruction_decision_prompts_enabled: bool = False
    proposal_discovery_enabled: bool = True
    proposal_discovery_prompts_enabled: bool = True
    wiki_aware_discovery_enabled: bool = True
    # Collaborative document building: arc proposal → slide negotiation → structure agreement.
    collaborative_building_enabled: bool = True
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
    tavily_api_key: str = ""
    tavily_provider_enabled: bool = True
    lp_library_local_path: str = ""
    policy_evaluator_version: str = "policy-v2"
    policy_classifier_threshold: float = 0.5
    policy_enforce_enabled: bool = True
    policy_bundle_path: str = ""
    # When True, legacy (non-agentic) path requires run_contract.nodes to be populated. Default False.
    policy_require_contract_nodes: bool = False
    event_contract_strict: bool = True
    retry_cooldown_threshold_sec: float = 20.0
    run_retry_indefinite_for_scheduled: bool = False

    # Deliverable quality contracts (config/quality_contracts/*.json) + registry-driven critique/revise loops.
    quality_contracts_dir: str = ""
    deliverable_quality_enabled: bool = True
    deliverable_quality_max_revision_rounds: int = 2
    # Framework-level deliverable architecture rollout flags.
    enable_deliverable_registry: bool = True
    enable_unified_quality_framework: bool = True
    enable_content_enrichment_engine: bool = True
    # Feature flag for PPTX structural vision critic (fail-open when disabled or unavailable).
    pptx_visual_critic_enabled: bool = True
    # Optional model override for PPTX visual critic; empty uses ANTHROPIC_CLAUDE_MODEL.
    pptx_visual_critic_model: str = ""
    # Feature flag for new artifact-tool-based PPTX renderer (executive-quality slides with composed layouts).
    # When enabled, uses artifact-tool Presentation with compose-first layouts instead of fixed python-pptx templates.
    pptx_artifact_renderer_enabled: bool = True
    # Feature flag for the editorial deck theme (typography-led consulting design language).
    # When enabled, decks with an unset deck_theme default to "editorial"; classic remains
    # reachable via brand_override.deck_theme. Fail-soft: falls back to classic on any error.
    pptx_editorial_theme_enabled: bool = True
    # Visual critic mode for PPTX: "auto" uses pixel path when soffice+pypdfium2 are available,
    # else falls back to metadata; "pixel" forces pixel path; "metadata" uses structural metadata only.
    pptx_visual_critic_mode: str = "auto"
    # When True, unsupported numeric claims from PPTX evidence validation fail the render QA gate.
    # When False, evidence signals remain advisory metadata.
    pptx_evidence_hard_fail_enabled: bool = False
    # When True, deck.pdf is produced by converting the rendered PPTX with LibreOffice
    # (pixel-faithful); the ReportLab outline renderer remains the fail-open fallback.
    deck_pdf_via_soffice_enabled: bool = True
    soffice_convert_timeout_sec: float = 120.0
    # Optional explicit path to the LibreOffice ``soffice`` binary. When unset,
    # discovery falls back to PATH then common install locations. Set this when
    # the worker runs with a minimal PATH and cannot find soffice automatically.
    soffice_binary_path: str = ""
    # Feature flags for the DOCX/XLSX composer paths (theme tokens, topic palette,
    # per-format QA). When enabled, the deliverable uses the composer; on any error
    # it falls back to the legacy render path. Mirrors pptx_editorial_theme_enabled.
    docx_composer_enabled: bool = True
    xlsx_composer_enabled: bool = True
    # Post-render artifact verification (citations, code-as-document, sparse PPTX text).
    final_artifact_qa_enabled: bool = True
    # Intent-aware deliverable archetype (advisory POV vs process doc vs proposal).
    deliverable_archetype_enabled: bool = True
    # Feature flag for narrative-coherence LLM critique blend (fail-open when disabled or unavailable).
    # When enabled, a short LLM critique augments the deterministic issues list
    # before the narrative score is aggregated.
    narrative_llm_critique_enabled: bool = True
    # Maximum issues taken from the LLM critique blend per evaluation.
    narrative_llm_critique_max_issues: int = 4

    upload_max_bytes: int = 50 * 1024 * 1024

    # Outbound HTTP (wiki URL ingest / refresh) — SSRF limits
    http_fetch_max_bytes: int = 2_000_000
    http_fetch_timeout_sec: float = 15.0
    # Comma-separated lowercase hostnames; empty = any public https host (still IP/DNS blocked)
    http_fetch_allowed_hosts: str = ""
    zip_max_uncompressed_bytes: int = 100 * 1024 * 1024

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
        "proposal_discovery_enabled",
        "proposal_discovery_prompts_enabled",
        "wiki_aware_discovery_enabled",
        "collaborative_building_enabled",
        "scratchpad_visibility_enabled",
        "strategy_options_planning_enabled",
        "wiki_meta_schema_versioning_enabled",
        "wiki_evented_graph_rebuild_enabled",
        "wiki_evented_graph_rebuild_fallback_sync_enabled",
        "wiki_health_scorecard_enabled",
        "wiki_storyline_canvas_enabled",
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
        "enable_deliverable_registry",
        "enable_unified_quality_framework",
        "enable_content_enrichment_engine",
        "pptx_visual_critic_enabled",
        "pptx_artifact_renderer_enabled",
        "pptx_editorial_theme_enabled",
        "pptx_evidence_hard_fail_enabled",
        "deck_pdf_via_soffice_enabled",
        "docx_composer_enabled",
        "xlsx_composer_enabled",
        "final_artifact_qa_enabled",
        "deliverable_archetype_enabled",
        "narrative_llm_critique_enabled",
        "structured_logging_enabled",
        "run_queue_embed_redis_consumer",
        "run_queue_startup_reconcile",
        "swarm_git_worktrees_enabled",
        "swarm_execute_custom_tasks_enabled",
        "subagent_narrative_thinking_enabled",
        "prompt_compression_enabled",
        "prompt_compression_log_verbose",
        "conversation_digest_tiered_compaction_enabled",
        "conversation_digest_sectioned_assembly_enabled",
        "conversation_digest_exclude_stale_sources",
        "tavily_provider_enabled",
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
    def _empty_audit_log_none(cls, v: Any) -> str | None:
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
        secret_raw = (self.jwt_secret or "").strip()
        secret_lower = secret_raw.lower()
        bad = ("", "change-me", "changeme")
        if secret_lower in bad or len(secret_raw) < 32:
            raise ValueError(
                "JWT_SECRET must be set to a strong secret (minimum 32 characters, not 'change-me'). "
                "For local development run `make dev.secret` or: "
                "python -c \"import secrets; print(secrets.token_urlsafe(32))\" and add JWT_SECRET to .env"
            )
        if not (self.database_url or "").strip():
            raise ValueError("DATABASE_URL must not be empty")
        if self.run_queue_backend not in {"local", "redis"}:
            raise ValueError("RUN_QUEUE_BACKEND must be 'local' or 'redis'")
        for origin in self.cors_origins_list:
            if origin.strip() == "*" or origin.strip().lower() == "*":
                raise ValueError(
                    "CORS_ORIGINS must not contain '*' — the API uses credential-bearing requests; "
                    "list explicit browser origins (e.g. http://localhost:3000)."
                )
        env_name = (self.processdoc_env or "development").strip().lower()
        if env_name in ("production", "prod", "staging"):
            if not self.cors_origins_list:
                raise ValueError(
                    "CORS_ORIGINS must list at least one explicit browser origin when "
                    "PROCESSDOC_ENV is production or staging (wildcard credentials are unsafe)."
                )
            if self.bash_tool_enabled:
                raise ValueError("BASH_TOOL_ENABLED must be false in production and staging.")
            if self.run_queue_backend == "redis" and self.database_url.strip().lower().startswith("sqlite"):
                raise ValueError(
                    "RUN_QUEUE_BACKEND=redis with a sqlite DATABASE_URL is not supported in production/staging: "
                    "SQLite's file-level locking will serialize concurrent request/SSE connections under load. "
                    "Set DATABASE_URL to a Postgres URL (see docker-compose.yml) before enabling the Redis queue."
                )
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


def log_wiki_config_warnings() -> None:
    """Warn when LP wiki is writable by any authenticated user due to missing allowlist."""
    import logging

    log = logging.getLogger("processdoc.config")
    raw = (getattr(settings, "wiki_lp_admin_emails", None) or "").strip()
    env = (getattr(settings, "processdoc_env", "development") or "development").strip().lower()
    if not raw and env == "development":
        log.warning(
            "WIKI_LP_ADMIN_EMAILS is not configured: any authenticated user can mutate the "
            "shared leading-practice wiki (development mode). Set WIKI_LP_ADMIN_EMAILS or "
            "PROCESSDOC_ENV != development before deploying to staging/production."
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
    if settings.run_queue_backend == "redis" and du.startswith("sqlite"):
        log.warning(
            "RUN_QUEUE_BACKEND=redis with a sqlite DATABASE_URL: SQLite's file-level locking will "
            "serialize concurrent request/SSE connections under real load (500-user target). Fine for "
            "local Redis-queue testing; switch DATABASE_URL to Postgres before staging/production "
            "(enforced there — see Settings._validate_secrets_and_urls)."
        )


def bash_allowlist_set() -> frozenset[str]:
    parts = {p.strip().lower() for p in settings.bash_allowlist_commands.split(",") if p.strip()}
    return frozenset(parts)


def text_editor_allowed_extensions_set() -> frozenset[str]:
    parts = {p.strip().lower() for p in settings.text_editor_allowed_extensions.split(",") if p.strip()}
    normalized = {(p if p.startswith(".") else f".{p}") for p in parts}
    return frozenset(normalized)
