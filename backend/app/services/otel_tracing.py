"""OpenTelemetry bootstrap (optional; requires opentelemetry-sdk when enabled)."""

from __future__ import annotations

import logging

from app.core.config import settings

_log = logging.getLogger("processdoc.otel")


def init_otel_if_enabled() -> None:
    """No-op unless ``settings.otel_sdk_enabled`` and packages are installed."""
    if not getattr(settings, "otel_sdk_enabled", False):
        return
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError:
        _log.warning("otel_sdk_enabled but opentelemetry-sdk is not installed; skipping OTel init")
        return
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _log.info("OpenTelemetry TracerProvider initialized (console exporter)")
