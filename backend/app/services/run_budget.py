"""Per-run aggregate LLM token budget (context-scoped)."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Generator

from app.core.exceptions import RunBudgetExceeded

_remaining: contextvars.ContextVar[int | None] = contextvars.ContextVar("run_llm_budget_remaining", default=None)


@contextmanager
def run_llm_budget(max_tokens: int) -> Generator[None, None, None]:
    if max_tokens <= 0:
        yield
        return
    tok = _remaining.set(int(max_tokens))
    try:
        yield
    finally:
        _remaining.reset(tok)


def charge_llm_usage(*, input_tokens: int, output_tokens: int) -> None:
    rem = _remaining.get()
    if rem is None:
        return
    used = int(input_tokens or 0) + int(output_tokens or 0)
    new_val = int(rem) - used
    if new_val < 0:
        raise RunBudgetExceeded("Run LLM token budget exhausted")
    _remaining.set(new_val)


def get_remaining_token_budget() -> int | None:
    return _remaining.get()


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
