import logging
import time
import uuid

from fastapi import Request

from app.core.request_context import correlation_id_ctx

_log = logging.getLogger("processdoc.request")


async def request_timing_middleware(request: Request, call_next):
    correlation_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    tok = correlation_id_ctx.set(correlation_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        correlation_id_ctx.reset(tok)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Request-ID"] = correlation_id
    response.headers["X-Request-Duration-Ms"] = str(duration_ms)
    _log.info("%s %s %s %sms", correlation_id, request.method, request.url.path, duration_ms)
    return response
