# Production Hardening Plan (2026-04-21)

## Scope

This plan hardens the recently shipped chat persistence and run-event architecture work so it is safe to enable broadly in production. It focuses on rollout safety, migration readiness, regression prevention, observability, and operational reliability.

## Success Criteria

- Routing quality parity is maintained (no critical regressions across fixture and staging replay sets).
- Context assembly latency remains within SLO budgets at p95/p99.
- Context trace and resume diagnostics are available for incident triage.
- Feature flags allow independent rollback of each new subsystem.
- Migration and index changes are validated on staging-scale data.

## One-Week Execution Plan

### Day 1 - Rollout Controls and Baselines

- Finalize feature-flag matrix by environment:
  - `conversation_digest_tiered_compaction_enabled`
  - `conversation_digest_sectioned_assembly_enabled`
  - `conversation_digest_exclude_stale_sources`
  - `conversation_digest_tiered_compaction_threshold_chars`
  - `conversation_source_freshness_ttl_seconds`
- Capture baseline metrics from current production-like traffic:
  - router decision distribution
  - digest assembly latency
  - run resume frequency and success
- Create rollback sheet with owner, trigger thresholds, and exact flag flips.

### Day 2 - Migration and Data Safety

- Apply `015_conversation_message_source_freshness` on staging snapshot.
- Validate index behavior and query plans for:
  - conversation message retrieval by conversation and time
  - any reads touching `source_type` and `source_freshness_at`
- Optional backfill dry-run:
  - infer `source_type` from message metadata kind
  - set `source_freshness_at = created_at + TTL` for eligible historical rows
- Document migration timing, lock profile, and rollback mechanics.

### Day 3 - Regression and Contract Coverage

- Add/expand snapshot fixtures for digest outputs:
  - tiered compaction trace tiers and dropped-source patterns
  - sectioned digest headings and budget behavior
  - stale source inclusion/exclusion boundaries
- Add router parity test harness:
  - compare decisions from legacy digest vs new digest modes
  - classify acceptable vs non-acceptable divergences
- Add API contract tests for:
  - `GET /runs/{project_id}/{run_id}/context_trace`
  - required trace fields and null-state handling.

### Day 4 - Observability and Alerting

- Build dashboards:
  - compaction tier frequency and char ratios
  - stale source exclusion count
  - sectioned assembly activation rates
  - `resume_state_loaded` events and downstream outcomes
- Add alerts:
  - sudden increase in `failed` after resume
  - missing `context_trace` for runs above threshold size
  - digest latency p95/p99 regression
- Confirm diagnostic drill-down can answer:
  - what was dropped
  - which tier applied
  - whether stale filtering affected evidence.

### Day 5 - Staging Replay and Canary

- Replay long and noisy conversation fixtures in staging:
  - 100+ turn histories
  - mixed stale/fresh discovery signals
  - repeated resume scenarios
- Canary enablement order:
  1. trace-only visibility (flags off where applicable)
  2. tiered compaction for small cohort
  3. sectioned assembly for same cohort
  4. stale exclusion after stability confirmation
- Compare against success criteria and sign off with owners.

## Workstreams and Owners

- App/API owner: flag rollout, router parity, endpoint contract checks.
- Data owner: migration, backfill, index verification.
- Reliability owner: dashboards, alerts, canary and rollback execution.
- QA owner: replay suite execution and defect triage.

## Test Matrix

- Unit:
  - compaction/trace behavior
  - freshness classification and TTL edges
  - memory profile persistence and retrieval
  - run resume event emission (`resume_state_loaded`)
- Integration:
  - conversation message lifecycle with checkpoints
  - run event stream plus context trace retrieval
  - router decisions with aggregated profile injection
- Staging replay:
  - historical conversation transcripts and run resumes
  - compacted vs non-compacted routing comparison.

## Rollout Order

1. Enable diagnostics and traces first.
2. Enable tiered compaction for canary.
3. Enable sectioned assembly for canary.
4. Enable stale-source exclusion with conservative TTL.
5. Expand traffic incrementally after each 24-hour stability window.

## Rollback Plan

- Immediate rollback triggers:
  - critical routing regressions
  - digest latency p99 breach
  - elevated failed runs post-resume
- Rollback actions:
  - disable sectioned assembly
  - disable tiered compaction
  - disable stale-source exclusion
  - keep traces on for diagnosis
- Post-rollback:
  - export affected run IDs and traces
  - perform root-cause analysis within one business day.

## Deliverables by End of Week

- Validated staging migration runbook.
- Passing regression and parity test reports.
- Live dashboards and alert policies.
- Signed canary report with go/no-go recommendation.
- Updated operator notes for flags, rollback, and diagnostics.
