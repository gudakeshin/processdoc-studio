"""Domain HTTP-oriented exceptions (mapped to JSON responses in main)."""


class ProcessDocError(Exception):
    """Base for domain errors in workers and services (non-HTTP)."""


class RunBudgetExceeded(ProcessDocError):
    """Raised when the per-run aggregate LLM token budget is exhausted."""


class ProcessDocHTTPException(Exception):
    """Raise with HTTP status and JSON-serializable detail (str or dict)."""

    def __init__(self, status_code: int, detail: str | dict) -> None:
        self.status_code = int(status_code)
        self.detail = detail
        super().__init__(str(detail))


class NotFoundError(ProcessDocHTTPException):
    def __init__(self, message: str = "Not found") -> None:
        super().__init__(404, message)


class ConflictError(ProcessDocHTTPException):
    def __init__(self, message: str = "Conflict") -> None:
        super().__init__(409, message)


class PayloadTooLargeError(ProcessDocHTTPException):
    def __init__(self, message: str = "File too large") -> None:
        super().__init__(413, message)


class UnsupportedMediaError(ProcessDocHTTPException):
    def __init__(self, message: str = "Unsupported file type") -> None:
        super().__init__(415, message)


class ValidationError(ProcessDocHTTPException):
    def __init__(self, message: str = "Validation failed") -> None:
        super().__init__(422, message)


class ExternalServiceError(ProcessDocHTTPException):
    def __init__(self, message: str = "External service failed") -> None:
        super().__init__(503, message)


class AuthorizationError(ProcessDocHTTPException):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(403, message)
