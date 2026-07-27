import logging
import time
import uuid

from fastapi import Request

from app.core.request_context import correlation_id_ctx
from app.services.otel_tracing import start_span

_log = logging.getLogger("processdoc.request")


async def request_timing_middleware(request: Request, call_next):
    correlation_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    tok = correlation_id_ctx.set(correlation_id)
    start = time.perf_counter()
    route = request.url.path
    method = request.method
    response = None
    try:
        with start_span(
            "http.request",
            attributes={
                "http.method": method,
                "http.route": route,
                "correlation_id": correlation_id,
            },
        ):
            response = await call_next(request)
    finally:
        correlation_id_ctx.reset(tok)
    if response is None:
        raise RuntimeError("request handler returned no response")  # pragma: no cover
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Request-ID"] = correlation_id
    response.headers["X-Request-Duration-Ms"] = str(duration_ms)
    _log.info("%s %s %s %sms", correlation_id, method, route, duration_ms)
    return response
