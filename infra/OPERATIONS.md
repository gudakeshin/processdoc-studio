# Operations Baseline

## Concurrency definitions (“500 concurrent users”)

Capacity planning depends on **which** “500” you mean:

| Metric | What it measures | What to size |
|--------|------------------|--------------|
| **Concurrent HTTP sessions** | Logged-in users with idle or occasional API calls | API replicas, DB pool, Redis for shared cache/queue |
| **Concurrent long-lived connections** | Open **SSE** (`/api/runs/.../stream`) or **WebSocket** (model/draw.io) per browser tab | Uvicorn/gunicorn **workers**, OS file descriptors, reverse-proxy **timeouts** (SSE/WebSocket stay open; defaults like 60s break streams) |
| **Concurrent agent runs** | Runs in `approved` / `running` (and queue depth) | `RUN_MAX_ACTIVE_*` in [backend/app/core/config.py](../backend/app/core/config.py), worker processes, LLM/provider quotas |

These are **not interchangeable**: 500 idle readers stress the connection layer differently from 500 simultaneous run approvals. Use [infra/load/README.md](load/README.md) harnesses to validate **REST burst**, **run soak**, and **SSE attach** against your target topology. See [infra/PRODUCTION_TOPOLOGY.md](PRODUCTION_TOPOLOGY.md) for Postgres pool, Redis queue, and proxy settings.

## Security Hardening
- Use JWT secret from environment and rotate quarterly.
- Restrict LP integration to read-only token scope.
- Keep DPDP consent ledger append-only.
- If `LANGFUSE_ENABLED=true`, redact secrets/PII before trace metadata and keep retention aligned with data policy.

## Performance
- Cache parsed text and search results in Redis.
- Keep context assembly within 32K chars.
- Limit sub-agent parallelism by output types.

## Reliability
- Store run manifests under workspace runs folder.
- Quarantine run when Gate 7 fails.
- Emit SSE events for all key states.
- Keep Langfuse optional; metrics/SSE must continue working if Langfuse is unreachable.

## Rollout Gates
1. Unit and integration tests pass.
2. Health/metrics endpoints pass probes.
3. Gate 7 quarantine path validated in staging.
4. 500-user soak + SLO gate pass.

## 500-user Soak and SLO Gate
- See [load/README.md](load/README.md) for **REST burst**, **SSE stream smoke**, and soak scripts.
- Generate soak report:
  - `BASE_URL=http://localhost:8000 AUTH_TOKEN=<token> PROJECT_ID=<pid> python infra/load/soak_500_runs.py > infra/load/last_soak_report.json`
- Evaluate release gate:
  - `python infra/load/slo_gate.py --soak-report infra/load/last_soak_report.json --metrics-url http://localhost:8000/metrics`
- Default pass thresholds:
  - p95 latency <= 2000 ms
  - error rate <= 3%
  - queue depth <= 250
