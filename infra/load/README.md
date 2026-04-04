# Load and soak harnesses

Use these scripts against a **running** API (`uvicorn` or production). They validate REST throughput, run lifecycle under concurrency, and short-lived **SSE** attachments (connection churn).

## Prerequisites

- Python 3.11+ (stdlib only for `rest_burst.py` and `sse_stream_smoke.py`; `soak_500_runs.py` is also stdlib).
- `AUTH_TOKEN`: JWT **access** token (`typ: access`), not refresh.
- For soak and SSE smoke: a `PROJECT_ID` the user can access; for SSE, a `RUN_ID` in that project.

## Scripts

### `rest_burst.py` — concurrent GET `/health`

Measures baseline HTTP concurrency (no auth). Tune `CONCURRENCY` and compare p95/error rate with `DATABASE_POOL_*`, Uvicorn `--workers`, and Postgres `max_connections`.

```bash
BASE_URL=http://localhost:8000 CONCURRENCY=200 python infra/load/rest_burst.py
```

### `sse_stream_smoke.py` — concurrent SSE opens on `/api/runs/.../stream`

Opens many streams with `?token=` (same mechanism as the browser `EventSource`). Each worker reads a small initial chunk then closes. Use this to stress **connection limits** and proxy timeouts before a full soak.

```bash
BASE_URL=http://localhost:8000 AUTH_TOKEN=... PROJECT_ID=... RUN_ID=... \
  CONCURRENT_STREAMS=100 python infra/load/sse_stream_smoke.py
```

If streams fail with 502/504, increase reverse-proxy **read timeouts** and OS `ulimit` for open files (see [../PRODUCTION_TOPOLOGY.md](../PRODUCTION_TOPOLOGY.md)).

### `soak_500_runs.py` — 500-user run lifecycle soak

Creates runs, approves, polls events, lists runs — see [../OPERATIONS.md](../OPERATIONS.md) for the SLO gate command.

```bash
BASE_URL=http://localhost:8000 AUTH_TOKEN=... PROJECT_ID=... \
  CONCURRENCY_USERS=500 ITERATIONS_PER_USER=2 \
  python infra/load/soak_500_runs.py > infra/load/last_soak_report.json
```

### `slo_gate.py` — evaluate soak + metrics

```bash
python infra/load/slo_gate.py --soak-report infra/load/last_soak_report.json \
  --metrics-url http://localhost:8000/metrics
```

## Tuning knobs (after measuring)

| Symptom | Direction |
|--------|-----------|
| DB connection errors | Lower `DATABASE_POOL_SIZE` / workers, or raise Postgres `max_connections` |
| 429 on run create | Raise `RUN_MAX_ACTIVE_*` only if workers and providers can sustain load |
| SSE drops behind nginx | Raise `proxy_read_timeout`, disable `proxy_buffering` for SSE |
| Stale cache across nodes | Redis required; set `CACHE_ALLOW_MEMORY_FALLBACK=false` |
