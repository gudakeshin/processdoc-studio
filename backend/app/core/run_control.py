"""Run lifecycle control (cooperative cancellation)."""


class RunAborted(Exception):
    """Raised when a run is aborted mid-coordinator via `abort_check`."""

    def __init__(self, message: str = "abort_requested") -> None:
        super().__init__(message)
        self.reason = message
