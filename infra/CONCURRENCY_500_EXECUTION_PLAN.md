# 500+ Concurrent Users Execution Plan

Date: 2026-03-26  
Scope: Execute scalability hardening in five phases with measurable gates.

## Objectives

- Sustain 500+ concurrent active users across API, run execution, realtime channels, and excel/model workflows.
- Keep p95 user-visible update latency <= 2s for realtime model/dashboard updates.
- Avoid silent data loss under retries, worker restarts, or network/provider instability.

## Phase 1 - Distributed run execution queue

- Replace in-process thread execution with a distributed worker queue backed by Redis.
- Move run execution (`Coordinator`) to worker consumers with idempotent job IDs.
- Add queue-level retry/backoff policy and dead-letter handling.
- Keep API contract stable: `/approve` still triggers execution, now via enqueue.

Exit gates:
- Parallel run throughput scales across multiple worker processes.
- Duplicate approvals do not duplicate execution.
- Queue failures are visible via metrics and operator endpoints.

## Phase 2 - Shared state and storage hardening

- Move hot-path mutable state away from process-local memory/files where contention is high.
- Keep artifacts in durable storage with explicit write contracts.
- Use DB-backed coordination primitives for run status transitions and locks.

Exit gates:
- Multi-instance API deployments remain consistent.
- Restarting any node does not orphan run lifecycle state.

## Phase 3 - Realtime fanout scaling

- Introduce Redis pub/sub (or stream-based fanout) between producers and websocket/SSE gateways.
- Support horizontal scaling of websocket nodes with shared event distribution.
- Preserve monotonic event IDs and replay semantics.

Exit gates:
- Connection count scales horizontally without sticky-session dependency.
- Reconnect/replay produces ordered, gap-free event recovery.

## Phase 4 - Admission control and fairness

- Implement request rate limits and per-project/per-user concurrency caps.
- Add backpressure semantics for heavy operations (excel sync/import/export).
- Define priority tiers and guardrails for noisy-neighbor isolation.

Exit gates:
- System degrades gracefully under load spikes.
- One tenant/project cannot starve others.

## Phase 5 - Performance validation and SLO enforcement

- Add load/soak tests for:
  - API auth/project/run lifecycle
  - run queue saturation
  - websocket/SSE concurrency
  - excel sync conflict workflows
- Track and alert on SLOs: p95 latency, error rate, queue lag, retry rate, WS health.
- Add release gate checklist for scale readiness.

Exit gates:
- 500+ concurrent users pass soak test with agreed SLO thresholds.
- Observability dashboards and alerts are production-ready.

## Implementation Sequencing

1. Phase 1 + baseline performance test
2. Phase 2 data/coordination hardening
3. Phase 3 realtime fanout scale
4. Phase 4 fairness/backpressure controls
5. Phase 5 soak tests, SLO gate, rollout

## Key technical risks and mitigations

- Risk: Duplicate run execution after retries  
  Mitigation: idempotency keys + status transition checks in DB.

- Risk: Event ordering regressions across nodes  
  Mitigation: strict event ID monotonicity and replay contract tests.

- Risk: Queue backlog during burst workloads  
  Mitigation: autoscaling workers + queue depth alarms + admission controls.

- Risk: Excel sync hot spots under enterprise usage  
  Mitigation: per-model sync throttling and conflict-first backpressure.

## Immediate next implementation tasks

- Introduce queue abstraction interface and Redis-backed implementation.
- Refactor `maybe_start_run_execution` call path to enqueue jobs.
- Add worker process entrypoint and health probes.
- Add queue lag and worker throughput metrics to observability endpoint.
