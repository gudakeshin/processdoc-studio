"""OpenTelemetry bootstrap (optional; requires opentelemetry-sdk when enabled)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import settings

_log = logging.getLogger("processdoc.otel")
_initialized = False


def init_otel_if_enabled() -> None:
    """No-op unless ``settings.otel_sdk_enabled`` and packages are installed."""
    global _initialized
    if not getattr(settings, "otel_sdk_enabled", False):
        return
    if _initialized:
        return
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError:
        _log.warning("otel_sdk_enabled but opentelemetry-sdk is not installed; skipping OTel init")
        return

    service_name = str(getattr(settings, "otel_service_name", "") or "processdoc-backend")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    endpoint = str(getattr(settings, "otel_exporter_otlp_endpoint", "") or "").strip()
    exporter: Any = None
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint)
            _log.info("OpenTelemetry OTLP exporter configured: %s", endpoint)
        except ImportError:
            _log.warning("OTLP endpoint set but opentelemetry-exporter-otlp is not installed")
    if exporter is None:
        exporter = ConsoleSpanExporter()
        _log.info("OpenTelemetry using ConsoleSpanExporter")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _initialized = True
    _log.info("OpenTelemetry TracerProvider initialized")


def get_tracer(name: str = "processdoc"):
    """Return an OTel tracer, or a no-op stand-in when OTel is disabled."""
    if not getattr(settings, "otel_sdk_enabled", False):
        return _NoopTracer()
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


@contextmanager
def start_span(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Context manager for a span; no-op when OTel is disabled."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes and hasattr(span, "set_attribute"):
            for k, v in attributes.items():
                try:
                    span.set_attribute(k, v)
                except Exception:  # noqa: S110 — attribute types vary by OTel backend
                    pass


class _NoopSpan:
    def set_attribute(self, *_a: Any, **_k: Any) -> None:
        return None

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, name: str, **_kwargs: Any) -> _NoopSpan:
        return _NoopSpan()
