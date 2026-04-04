from __future__ import annotations

from typing import Any

from app.core.config import settings

_CLIENT: Any | None = None


def _get_client() -> Any | None:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not settings.langfuse_enabled:
        return None
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    try:
        from langfuse import Langfuse  # type: ignore

        _CLIENT = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return _CLIENT
    except Exception:
        return None


def langfuse_event(
    *,
    trace_id: str,
    name: str,
    metadata: dict[str, Any] | None = None,
    level: str = "DEFAULT",
) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.trace(id=trace_id, metadata=metadata or {}).event(name=name, level=level, metadata=metadata or {})
    except Exception:
        return


def langfuse_span(
    *,
    trace_id: str,
    name: str,
    input_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
    status_message: str | None = None,
) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        span = client.trace(id=trace_id).span(name=name, input=input_payload or {})
        if output_payload is not None:
            span.update(output=output_payload)
        if status_message:
            span.update(status_message=status_message)
    except Exception:
        return
