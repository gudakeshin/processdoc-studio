"""Run lifecycle control (cooperative cancellation)."""

import threading
from collections.abc import Callable
from contextlib import contextmanager


class RunAborted(Exception):
    """Raised when a run is aborted mid-coordinator via `abort_check`."""

    def __init__(self, message: str = "abort_requested") -> None:
        super().__init__(message)
        self.reason = message


_abort_tls = threading.local()


@contextmanager
def abort_scope(abort_check: Callable[[], bool] | None):
    """Bind an ``abort_check`` callable to the current thread for the duration of the block.

    Shared by the coordinator (checkpoint polling) and the Claude SDK call sites
    (mid-stream polling) so a single ``abort_requested`` flag can halt a run whether
    it's between agent steps or in the middle of token generation.
    """
    prev: Callable[[], bool] | None = getattr(_abort_tls, "check", None)
    _abort_tls.check = abort_check
    try:
        yield
    finally:
        _abort_tls.check = prev


def poll_abort() -> None:
    """Raise ``RunAborted`` if the current thread's bound abort check reports True."""
    fn = getattr(_abort_tls, "check", None)
    if fn is not None and fn():
        raise RunAborted()
