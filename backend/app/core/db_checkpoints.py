"""Helpers for explicit DB flush/commit checkpoint tracing."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterator

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class DbCheckpointRun:
    """Tracks named checkpoints for one transactional flow."""

    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=perf_counter)

    def mark(self, stage: str, **data: Any) -> None:
        stage_name = str(stage or "").strip()
        if not stage_name:
            return
        event = {
            "stage": stage_name,
            "elapsed_ms": round((perf_counter() - self.started_at) * 1000, 2),
        }
        if data:
            event["data"] = data
        self.checkpoints.append(event)
        _LOG.debug("db_checkpoint stage=%s flow=%s data=%s", stage_name, self.name, data or {})

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metadata": dict(self.metadata),
            "checkpoints": list(self.checkpoints),
        }


@contextmanager
def checkpoint_scope(
    session: Session,
    name: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> Iterator[DbCheckpointRun]:
    """Open a checkpoint scope and roll back on unhandled errors."""
    run = DbCheckpointRun(name=str(name or "unnamed"), metadata=metadata or {})
    run.mark("scope_opened")
    try:
        yield run
        run.mark("scope_completed")
    except Exception as exc:
        run.mark("scope_failed", error=str(exc)[:300])
        # Keep callers simple: guarantee transaction cleanup on uncaught failure.
        session.rollback()
        _LOG.exception("db_checkpoint flow failed: %s", run.snapshot())
        raise
