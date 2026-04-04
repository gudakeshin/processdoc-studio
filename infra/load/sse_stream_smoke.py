#!/usr/bin/env python3
"""
Concurrent short-lived SSE connections to GET /api/runs/{project_id}/{run_id}/stream.

Uses ?token= for auth (browser EventSource-compatible). Each worker reads an initial
chunk then closes the connection to stress connection/proxy limits without long runtimes.

Usage:
  BASE_URL=http://localhost:8000 AUTH_TOKEN=... PROJECT_ID=... RUN_ID=... \\
    CONCURRENT_STREAMS=50 python infra/load/sse_stream_smoke.py
"""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import quote


@dataclass
class Sample:
    status_code: int
    latency_first_byte_ms: float
    ok: bool


def _open_stream(base: str, project_id: str, run_id: str, token: str, read_bytes: int) -> Sample:
    q = quote(token, safe="")
    url = f"{base}/api/runs/{project_id}/{run_id}/stream?after_event_id=0&token={q}"
    started = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            ttfb = (time.perf_counter() - started) * 1000.0
            _ = resp.read(read_bytes)
            ok = 200 <= resp.status < 300
            return Sample(status_code=resp.status, latency_first_byte_ms=ttfb, ok=ok)
    except urllib.error.HTTPError as exc:
        ttfb = (time.perf_counter() - started) * 1000.0
        return Sample(status_code=exc.code, latency_first_byte_ms=ttfb, ok=False)
    except Exception:
        ttfb = (time.perf_counter() - started) * 1000.0
        return Sample(status_code=0, latency_first_byte_ms=ttfb, ok=False)


def main() -> None:
    base = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    token = os.getenv("AUTH_TOKEN", "").strip()
    project_id = os.getenv("PROJECT_ID", "").strip()
    run_id = os.getenv("RUN_ID", "").strip()
    concurrent = max(1, int(os.getenv("CONCURRENT_STREAMS", "50")))
    read_bytes = max(64, int(os.getenv("SSE_READ_BYTES", "2048")))

    if not token or not project_id or not run_id:
        raise SystemExit("AUTH_TOKEN, PROJECT_ID, and RUN_ID are required")

    samples: list[Sample] = []
    started = time.time()

    with ThreadPoolExecutor(max_workers=concurrent) as pool:
        futures = [pool.submit(_open_stream, base, project_id, run_id, token, read_bytes) for _ in range(concurrent)]
        for fut in as_completed(futures):
            samples.append(fut.result())

    elapsed = time.time() - started
    latencies = [s.latency_first_byte_ms for s in samples]
    p95 = statistics.quantiles(latencies, n=100)[94] if len(latencies) >= 100 else max(latencies)
    errors = [s for s in samples if not s.ok]
    by_status: dict[int, int] = {}
    for s in samples:
        by_status[s.status_code] = by_status.get(s.status_code, 0) + 1

    report = {
        "concurrent_streams": concurrent,
        "duration_sec": round(elapsed, 2),
        "streams_total": len(samples),
        "errors_total": len(errors),
        "error_rate": round(len(errors) / max(1, len(samples)), 4),
        "p95_ttfb_ms": round(p95, 2),
        "status_counts": by_status,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
