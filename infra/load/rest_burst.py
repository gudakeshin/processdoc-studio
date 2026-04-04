#!/usr/bin/env python3
"""
Concurrent GET /health burst (no auth). Baseline for API + reverse-proxy capacity.

Usage:
  BASE_URL=http://localhost:8000 CONCURRENCY=200 REQUESTS_TOTAL=2000 python infra/load/rest_burst.py
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


@dataclass
class Sample:
    status_code: int
    latency_ms: float
    ok: bool


def _one(url: str) -> Sample:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            _ = resp.read()
            elapsed = (time.perf_counter() - started) * 1000.0
            return Sample(status_code=resp.status, latency_ms=elapsed, ok=200 <= resp.status < 300)
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        return Sample(status_code=exc.code, latency_ms=elapsed, ok=False)
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000.0
        return Sample(status_code=0, latency_ms=elapsed, ok=False)


def main() -> None:
    base = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    url = f"{base}/health"
    concurrency = max(1, int(os.getenv("CONCURRENCY", "100")))
    total = max(concurrency, int(os.getenv("REQUESTS_TOTAL", str(concurrency * 20))))

    samples: list[Sample] = []
    started = time.time()

    def worker() -> Sample:
        return _one(url)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker) for _ in range(total)]
        for fut in as_completed(futures):
            samples.append(fut.result())

    elapsed = time.time() - started
    latencies = [s.latency_ms for s in samples]
    p95 = statistics.quantiles(latencies, n=100)[94] if len(latencies) >= 100 else max(latencies)
    errors = [s for s in samples if not s.ok]
    by_status: dict[int, int] = {}
    for s in samples:
        by_status[s.status_code] = by_status.get(s.status_code, 0) + 1

    report = {
        "endpoint": url,
        "concurrency": concurrency,
        "requests_total": len(samples),
        "duration_sec": round(elapsed, 2),
        "rps": round(len(samples) / max(elapsed, 1e-6), 2),
        "errors_total": len(errors),
        "error_rate": round(len(errors) / max(1, len(samples)), 4),
        "p95_latency_ms": round(p95, 2),
        "status_counts": by_status,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
