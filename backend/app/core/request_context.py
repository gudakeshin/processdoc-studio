"""Request-scoped context (API workers only; background jobs have no correlation)."""

from __future__ import annotations

import contextvars

correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str | None:
    return correlation_id_ctx.get()
