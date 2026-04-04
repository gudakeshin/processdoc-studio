#!/usr/bin/env python3
"""
Release gate evaluator for 500-user readiness.

Inputs:
  - Soak JSON report file produced by soak_500_runs.py
  - Optional live backend /metrics endpoint
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        payload = resp.read().decode("utf-8")
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--soak-report", required=True, help="Path to soak json")
    parser.add_argument("--metrics-url", default="", help="Optional backend metrics endpoint")
    parser.add_argument("--max-p95-ms", type=float, default=2000.0)
    parser.add_argument("--max-error-rate", type=float, default=0.03)
    parser.add_argument("--max-queue-depth", type=int, default=250)
    args = parser.parse_args()

    with open(args.soak_report, "r", encoding="utf-8") as fh:
        soak = json.load(fh)
    if not isinstance(soak, dict):
        raise SystemExit("Invalid soak report payload")

    p95 = float(soak.get("p95_latency_ms") or 0)
    error_rate = float(soak.get("error_rate") or 1)

    queue_depth = 0
    if args.metrics_url:
        metrics = _fetch_json(args.metrics_url)
        run_queue = metrics.get("run_queue", {}) if isinstance(metrics.get("run_queue"), dict) else {}
        queue_depth = int(run_queue.get("depth") or 0)

    checks = {
        "p95_latency": p95 <= args.max_p95_ms,
        "error_rate": error_rate <= args.max_error_rate,
        "queue_depth": queue_depth <= args.max_queue_depth,
    }
    passed = all(checks.values())
    output = {
        "passed": passed,
        "thresholds": {
            "max_p95_ms": args.max_p95_ms,
            "max_error_rate": args.max_error_rate,
            "max_queue_depth": args.max_queue_depth,
        },
        "observed": {
            "p95_latency_ms": p95,
            "error_rate": error_rate,
            "queue_depth": queue_depth,
        },
        "checks": checks,
    }
    print(json.dumps(output, indent=2))
    if not passed:
        sys.exit(2)


if __name__ == "__main__":
    main()
