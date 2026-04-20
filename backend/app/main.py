import importlib.util
import json
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.core.exceptions import ProcessDocHTTPException

_backend_root = Path(__file__).resolve().parent.parent
_repo_root = _backend_root.parent
# Repo-root `.env` then `backend/.env` (backend wins on duplicate keys) so RUN_QUEUE_BACKEND / DATABASE_URL match what you edit at either location.
load_dotenv(_repo_root / ".env")
load_dotenv(_backend_root / ".env", override=True)

# All app-level imports MUST follow the two load_dotenv() calls above so that
# Settings() and other modules observe the final env-var state. Suppress E402
# for this file only (see [tool.ruff.lint.per-file-ignores] in pyproject.toml).
from app.api.routes import router
from app.api.wiki import router as wiki_router
from app.core.config import log_memory_config_warnings, log_run_queue_startup_config, settings
from app.core.deliverable import DeliverableRegistry
from app.core.deliverable_docx import DOCXDeliverable
from app.core.deliverable_pdf import PDFDeliverable
from app.core.deliverable_pptx import PPTXDeliverable
from app.core.deliverable_process_map import ProcessMapDeliverable
from app.core.deliverable_xlsx import XLSXDeliverable
from app.core.middleware import request_timing_middleware
from app.core.rate_limit import limiter
from app.core.request_context import get_correlation_id
from app.db.session import engine, init_db
from app.services.mcp.registry import shutdown_mcp_servers, startup_mcp_servers
from app.services.observability import prometheus_text
from app.services.observability import snapshot as observability_snapshot
from app.services.otel_tracing import init_otel_if_enabled
from app.services.run_worker import (
    admission_status,
    list_worker_heartbeats,
    queue_runtime_stats,
    reconcile_stalled_approved_runs_on_startup,
    start_execution_worker,
)
from app.services.scheduled_tasks import start_scheduler_worker


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
        }
        cid = get_correlation_id()
        if cid:
            payload["correlation_id"] = cid
        return json.dumps(payload, ensure_ascii=True)


if settings.structured_logging_enabled:
    root = logging.getLogger()
    if root.handlers:
        for h in root.handlers:
            h.setFormatter(JsonLogFormatter())



@asynccontextmanager
async def lifespan(_app: FastAPI):
    log_memory_config_warnings()
    log_run_queue_startup_config(
        repo_env_present=(_repo_root / ".env").is_file(),
        backend_env_present=(_backend_root / ".env").is_file(),
    )
    init_otel_if_enabled()
    init_db()
    if settings.enable_deliverable_registry:
        DeliverableRegistry.register("pptx", PPTXDeliverable())
        DeliverableRegistry.register("docx", DOCXDeliverable())
        DeliverableRegistry.register("xlsx", XLSXDeliverable())
        DeliverableRegistry.register("pdf", PDFDeliverable())
        DeliverableRegistry.register("process_map", ProcessMapDeliverable())
    await startup_mcp_servers()
    start_execution_worker()
    reconcile_stalled_approved_runs_on_startup()
    if settings.scheduler_enabled:
        start_scheduler_worker()
    yield
    await shutdown_mcp_servers()


app = FastAPI(
    title="ProcessDoc Studio API",
    version="0.2.0",
    lifespan=lifespan,
    description="Process documentation studio: projects, agentic runs, documents, models, and memory APIs.",
    openapi_tags=[
        {"name": "auth", "description": "Login, refresh tokens, and session identity."},
        {"name": "projects", "description": "Project CRUD and membership."},
        {"name": "runs", "description": "Run lifecycle, SSE streams, and artifacts."},
        {"name": "documents", "description": "Source document upload and listing."},
        {"name": "models", "description": "Excel-backed models and realtime collaboration."},
    ],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.middleware("http")(request_timing_middleware)

# Trust X-Forwarded-For from known upstream proxies so that request.client.host
# (and therefore SlowAPI's per-IP rate limit key) reflects the real caller when we
# run behind an ALB / nginx / Cloudflare. Off by default; operators must explicitly
# opt in AND set TRUST_FORWARDED_FOR_HOSTS to the proxy addresses.
if settings.trust_forwarded_for_enabled:
    try:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        _trusted = settings.trust_forwarded_for_hosts.strip() or "127.0.0.1"
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted)
    except Exception as _exc:  # noqa: BLE001
        logging.getLogger("app.main").warning(
            "trust_forwarded_for_enabled=true but ProxyHeadersMiddleware failed to install: %s",
            _exc,
        )


@app.exception_handler(ProcessDocHTTPException)
async def processdoc_http_exception_handler(_request, exc: ProcessDocHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

_cors_kw: dict = {
    "allow_origins": settings.cors_origins_list,
    "allow_credentials": True,
    "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    "allow_headers": [
        "Authorization",
        "Content-Type",
        "Accept",
        "Accept-Language",
        "Origin",
        "X-Requested-With",
        "X-Correlation-Id",
        "X-Request-Id",
    ],
    "expose_headers": [
        "Retry-After",
        "X-Admission-Queue-Depth",
        "X-Admission-Project-Limit",
        "X-Admission-Global-Limit",
        "X-Admission-User-Limit",
    ],
}
if settings.cors_allow_origin_regex:
    _cors_kw["allow_origin_regex"] = settings.cors_allow_origin_regex
app.add_middleware(CORSMiddleware, **_cors_kw)

app.include_router(router, prefix="/api")

app.include_router(wiki_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict:
    """Dependency readiness for orchestrators (no secrets in response)."""
    db_ok = False
    db_error: str | None = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_error = type(exc).__name__
    redis_ok: bool | None = None
    redis_error: str | None = None
    if settings.run_queue_backend == "redis":
        try:
            import redis

            r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            r.ping()
            redis_ok = True
        except Exception as exc:  # noqa: BLE001
            redis_ok = False
            redis_error = type(exc).__name__
    ready = db_ok and (redis_ok is None or redis_ok is True)
    return {
        "status": "ready" if ready else "degraded",
        "database": {"ok": db_ok, "error": db_error},
        "redis": {"required": settings.run_queue_backend == "redis", "ok": redis_ok, "error": redis_error},
        "run_queue": {
            "backend": settings.run_queue_backend,
            "embedded_redis_consumer": bool(getattr(settings, "run_queue_embed_redis_consumer", False)),
            "hint": (
                "With redis backend, either run python -m app.workers.run_execution_worker or set "
                "RUN_QUEUE_EMBED_REDIS_CONSUMER=true on the API (single-node only)."
                if settings.run_queue_backend == "redis"
                else "Local in-process queue worker is started with the API."
            ),
        },
    }


@app.get("/api/health/visual-qa")
def visual_qa_health() -> dict:
    return _visual_qa_health_payload()


@app.get("/api/health/bash-tool")
def bash_tool_health() -> dict:
    import shutil

    return {
        "bash_tool_enabled": settings.bash_tool_enabled,
        "bash_docker_enabled": settings.bash_docker_enabled,
        "docker_cli_available": bool(shutil.which("docker")),
        "audit_log_configured": bool(settings.bash_audit_log),
    }


@app.get("/api/health/text-editor-tool")
def text_editor_tool_health() -> dict:
    return {
        "text_editor_tool_enabled": settings.text_editor_tool_enabled,
        "max_characters": settings.text_editor_max_characters,
        "backup_enabled": settings.text_editor_backup_enabled,
        "audit_log_configured": bool(settings.text_editor_audit_log),
    }


def _visual_qa_health_payload() -> dict:
    pillow_available = importlib.util.find_spec("PIL") is not None
    pypdfium2_available = importlib.util.find_spec("pypdfium2") is not None
    soffice_path = shutil.which("soffice")
    all_ready = pillow_available and pypdfium2_available and bool(soffice_path)
    return {
        "status": "ok" if all_ready else "degraded",
        "visual_qa_strict_image_ready": all_ready,
        "dependencies": {
            "pillow": pillow_available,
            "pypdfium2": pypdfium2_available,
            "soffice": bool(soffice_path),
        },
        "paths": {"soffice": soffice_path},
    }


@app.get("/metrics")
def metrics() -> dict:
    return {
        "service": "processdoc-backend",
        "observability": observability_snapshot(),
        "run_queue": queue_runtime_stats(),
        "visual_qa": _visual_qa_health_payload(),
        "bash_tool": bash_tool_health(),
        "text_editor_tool": text_editor_tool_health(),
    }


@app.get("/metrics/prometheus", response_class=PlainTextResponse)
def metrics_prometheus() -> str:
    return prometheus_text()


@app.get("/workers/health")
def workers_health() -> dict:
    queue = queue_runtime_stats()
    return {
        "backend": queue.get("backend"),
        "healthy": queue.get("healthy"),
        "worker_count": queue.get("worker_count"),
        "workers": queue.get("workers") or list_worker_heartbeats(),
    }


@app.get("/admission/{project_id}")
def admission(
    project_id: str,
    user_id: str | None = None,
) -> dict:
    # Note: admission endpoint is public for quota checks; no auth required
    return admission_status(project_id, user_id=user_id)
