#!/usr/bin/env python3
"""
Lightweight 500-user soak harness for run lifecycle APIs.

Usage:
  BASE_URL=http://localhost:8000 AUTH_TOKEN=... PROJECT_ID=... python infra/load/soak_500_runs.py
"""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


@dataclass
class RequestSample:
    endpoint: str
    status_code: int
    latency_ms: float
    ok: bool


def _request(method: str, url: str, token: str, body: dict | None = None) -> RequestSample:
    started = time.perf_counter()
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url=url, data=payload, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            _ = resp.read()
            elapsed = (time.perf_counter() - started) * 1000.0
            return RequestSample(endpoint=url, status_code=resp.status, latency_ms=elapsed, ok=200 <= resp.status < 300)
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        return RequestSample(endpoint=url, status_code=exc.code, latency_ms=elapsed, ok=False)
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000.0
        return RequestSample(endpoint=url, status_code=0, latency_ms=elapsed, ok=False)


def _request_json(method: str, url: str, token: str, body: dict | None = None) -> tuple[RequestSample, dict]:
    started = time.perf_counter()
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url=url, data=payload, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            elapsed = (time.perf_counter() - started) * 1000.0
            parsed = json.loads(raw) if raw else {}
            return RequestSample(endpoint=url, status_code=resp.status, latency_ms=elapsed, ok=200 <= resp.status < 300), (
                parsed if isinstance(parsed, dict) else {}
            )
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        return RequestSample(endpoint=url, status_code=exc.code, latency_ms=elapsed, ok=False), {}
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000.0
        return RequestSample(endpoint=url, status_code=0, latency_ms=elapsed, ok=False), {}


def main() -> None:
    base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
    token = os.getenv("AUTH_TOKEN", "").strip()
    project_id = os.getenv("PROJECT_ID", "").strip()
    users = int(os.getenv("CONCURRENCY_USERS", "500"))
    iterations = int(os.getenv("ITERATIONS_PER_USER", "2"))
    instruction = os.getenv("RUN_INSTRUCTION", "Generate process documentation")
    if not token or not project_id:
        raise SystemExit("AUTH_TOKEN and PROJECT_ID are required")

    samples: list[RequestSample] = []
    samples_lock = threading.Lock()

    def user_flow(user_idx: int) -> None:
        for n in range(iterations):
            create, body = _request_json(
                "POST",
                f"{base_url}/api/runs",
                token,
                body={
                    "project_id": project_id,
                    "instruction": f"{instruction} (u{user_idx}-i{n})",
                    "output_types": [],
                },
            )
            with samples_lock:
                samples.append(create)
            if not create.ok:
                continue
            run_id = str(body.get("run_id") or "")
            if run_id:
                approve = _request("POST", f"{base_url}/api/runs/{project_id}/{run_id}/approve", token)
                with samples_lock:
                    samples.append(approve)
                stream = _request("GET", f"{base_url}/api/runs/{project_id}/{run_id}/events?after_event_id=0", token)
                with samples_lock:
                    samples.append(stream)
            list_runs = _request("GET", f"{base_url}/api/runs?project_id={project_id}", token)
            with samples_lock:
                samples.append(list_runs)

    started = time.time()
    with ThreadPoolExecutor(max_workers=users) as pool:
        futures = [pool.submit(user_flow, idx) for idx in range(users)]
        for fut in as_completed(futures):
            fut.result()
    elapsed = time.time() - started

    if not samples:
        raise SystemExit("No samples recorded")

    latencies = [s.latency_ms for s in samples]
    p95 = statistics.quantiles(latencies, n=100)[94] if len(latencies) >= 100 else max(latencies)
    errors = [s for s in samples if not s.ok]
    by_status: dict[int, int] = {}
    for sample in samples:
        by_status[sample.status_code] = by_status.get(sample.status_code, 0) + 1

    report = {
        "started_at_epoch": int(started),
        "duration_sec": round(elapsed, 2),
        "users": users,
        "iterations_per_user": iterations,
        "requests_total": len(samples),
        "errors_total": len(errors),
        "error_rate": round(len(errors) / max(1, len(samples)), 4),
        "p95_latency_ms": round(p95, 2),
        "status_counts": by_status,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
