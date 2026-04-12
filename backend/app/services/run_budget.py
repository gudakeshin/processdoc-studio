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
    usage = getattr(message, "usage", None)
    if usage is None:
        return 0, 0
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    return inp, out
