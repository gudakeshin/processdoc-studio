"""Per-run aggregate LLM token budget and usage tracking (context-scoped)."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from app.core.exceptions import RunBudgetExceeded


class _RunTokenUsage:
    """Thread-safe per-run token accumulator.

    Stored *by reference* in a ContextVar so child threads that copy the context
    share the same Python object.  All mutations are therefore visible across
    threads without needing to propagate ContextVar changes back.
    """

    __slots__ = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "_lock")

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self._lock = threading.Lock()

    def charge(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        with self._lock:
            self.input_tokens += int(input_tokens or 0)
            self.output_tokens += int(output_tokens or 0)
            self.cache_read_tokens += int(cache_read_tokens or 0)
            self.cache_creation_tokens += int(cache_creation_tokens or 0)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read_tokens,
                "cache_creation_tokens": self.cache_creation_tokens,
            }


# Budget remaining (int) — separate from usage tracking
_remaining: contextvars.ContextVar[int | None] = contextvars.ContextVar("run_llm_budget_remaining", default=None)

# The mutable usage accumulator for the current run — stored by reference so
# child threads see and update the same object.
_active_usage: contextvars.ContextVar[_RunTokenUsage | None] = contextvars.ContextVar("run_active_usage", default=None)

# Module-level registry for live polling: maps run_id → usage object while the run is executing.
_live_usage_registry: dict[str, _RunTokenUsage] = {}
_live_registry_lock = threading.Lock()

# Project-level accumulator: maps project_id → usage object.
# Accumulates tokens from *all* Claude calls for a project (chat + runs) during the server process.
_project_accumulators: dict[str, _RunTokenUsage] = {}
_project_accumulators_lock = threading.Lock()

# ContextVar pointing to the current project's accumulator (so charge_llm_usage can charge it).
_active_project_usage: contextvars.ContextVar[_RunTokenUsage | None] = contextvars.ContextVar(
    "run_active_project_usage", default=None
)


@contextmanager
def run_llm_budget(max_tokens: int, *, run_id: str | None = None) -> Generator[None, None, None]:
    usage = _RunTokenUsage()
    tok_usage = _active_usage.set(usage)
    if run_id:
        with _live_registry_lock:
            _live_usage_registry[run_id] = usage
    try:
        if max_tokens <= 0:
            yield
            return
        tok = _remaining.set(int(max_tokens))
        try:
            yield
        finally:
            _remaining.reset(tok)
    finally:
        _active_usage.reset(tok_usage)
        if run_id:
            with _live_registry_lock:
                _live_usage_registry.pop(run_id, None)


def charge_llm_usage(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> None:
    rem = _remaining.get()
    if rem is not None:
        used = int(input_tokens or 0) + int(output_tokens or 0)
        new_val = int(rem) - used
        if new_val < 0:
            raise RunBudgetExceeded("Run LLM token budget exhausted")
        _remaining.set(new_val)
    usage = _active_usage.get()
    if usage is not None:
        usage.charge(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
    proj_usage = _active_project_usage.get()
    if proj_usage is not None:
        proj_usage.charge(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )


def get_remaining_token_budget() -> int | None:
    return _remaining.get()


def get_run_usage() -> dict[str, int]:
    """Return raw per-category token counts accumulated in the current run context."""
    usage = _active_usage.get()
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}
    return usage.snapshot()


def get_live_usage(run_id: str) -> dict[str, int] | None:
    """Return live token counts for an in-progress run, or None if the run is not active."""
    with _live_registry_lock:
        usage = _live_usage_registry.get(run_id)
    return usage.snapshot() if usage is not None else None


@contextmanager
def project_token_context(project_id: str) -> Generator[None, None, None]:
    """Context manager that routes all charge_llm_usage calls into a per-project accumulator.

    Idempotent: re-entering for the same project_id reuses the existing accumulator,
    so run_worker and conversation handlers both contribute to the same total.
    """
    with _project_accumulators_lock:
        if project_id not in _project_accumulators:
            _project_accumulators[project_id] = _RunTokenUsage()
        proj_usage = _project_accumulators[project_id]
    tok = _active_project_usage.set(proj_usage)
    try:
        yield
    finally:
        _active_project_usage.reset(tok)


def get_project_usage(project_id: str) -> dict[str, int]:
    """Return accumulated token counts for a project across all chat + run calls."""
    with _project_accumulators_lock:
        usage = _project_accumulators.get(project_id)
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}
    return usage.snapshot()


def extract_usage_counts(message: Any) -> tuple[int, int]:
    """Return ``(input_tokens, output_tokens)`` charged against the per-run LLM budget.

    Prompt-caching behavior (Anthropic beta): ``cache_read_input_tokens`` are billed at a
    small fraction of normal input cost and ``cache_creation_input_tokens`` are billed at a
    ~25% premium. To keep the aggregate run budget a conservative ceiling (never
    under-charge), we fold cache-read into the input charge at a 10% weight and cache-create
    at a 125% weight; both are also logged at DEBUG for observability. If you change these
    weights, update ``docs/token_budget.md`` / README accordingly.
    """
    usage = getattr(message, "usage", None)
    if usage is None:
        return 0, 0
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_create = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    if cache_read or cache_create:
        import logging

        logging.getLogger(__name__).debug(
            "Prompt cache — read=%d tokens, creation=%d tokens (%.0f%% saved)",
            cache_read,
            cache_create,
            100.0 * cache_read / max(1, inp + cache_read + cache_create),
        )
    billed_input = inp + (cache_read // 10) + ((cache_create * 5) // 4)
    return billed_input, out
