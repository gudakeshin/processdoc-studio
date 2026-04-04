# Step 2 Priority 1 - QA / Guardrails / DPDP Hardening Tickets

Date: 2026-03-26  
Objective: Harden quality and compliance behavior for QA loop, guardrails, and DPDP to align with strict v4 release gates.

## T1 - Guardrails fallback checks in local mode (remove blanket pass)

- Priority: P0
- Problem:
  - In local mode (Claude disabled), gates 1-6 can pass by default, which is too permissive.
- Scope:
  - Add deterministic minimum checks per gate for local mode.
- Target files:
  - `backend/app/services/guardrails.py`
  - `backend/app/services/tool_registry.py`
- API/event impact:
  - Preserve existing `guardrail_event` schema; improve reasons payload for each gate.
- Acceptance criteria:
  - Gates 1-6 return deterministic pass/fail in local mode.
  - Failures identify gate-specific reason (not generic fallback text).
  - Existing run flow remains backward compatible.
- Suggested checks:
  - Gate 1: source grounding presence ratio from artifacts/context.
  - Gate 2: hallucination heuristics (claims without references).
  - Gate 3: brand style lint (tone/phrasing constraints).
  - Gate 4: reference format and resolvability checks.
  - Gate 5: plagiarism advisory threshold heuristic.
  - Gate 6: style enforcer checks for template conformance.

## T2 - QA corrective loop with actionable remediation

- Priority: P0
- Problem:
  - QA iterates scoring but does not consistently generate actionable rewrite instructions and route correction.
- Scope:
  - Extend QA output with structured remediation directives.
  - Feed directives to coordinator for one bounded correction pass per failing output.
- Target files:
  - `backend/app/services/qa.py`
  - `backend/app/agents/coordinator.py`
  - `backend/app/agents/subagents.py`
- API/event impact:
  - Optional extension in `qa_report` event payload: `remediation_instructions`.
- Acceptance criteria:
  - On QA fail, coordinator triggers bounded correction attempt.
  - Retry is per-output and includes explicit instruction bundle.
  - QA report records pre/post scores and whether remediation converged.

## T3 - DPDP detection quality upgrade path (beyond regex baseline)

- Priority: P0
- Problem:
  - Current DPDP detection is regex-centric, insufficient for strict compliance confidence.
- Scope:
  - Add pluggable detector interface and confidence scoring.
  - Keep regex detector as baseline fallback.
- Target files:
  - `backend/app/services/dpdp.py`
  - `backend/app/core/state.py` (if state additions needed)
  - `backend/app/api/dpdp.py` (response model extensions)
- API/event impact:
  - Extend DPDP report with detector metadata:
    - `detector_name`
    - `detector_confidence`
    - `entity_confidence`
- Acceptance criteria:
  - DPDP report includes confidence and detector provenance.
  - Gate 7 decision references confidence policy threshold.
  - Existing consumers remain compatible (additive schema changes).

## T4 - Quarantine governance hardening

- Priority: P1
- Problem:
  - Quarantine path exists but governance metadata can be strengthened.
- Scope:
  - Persist immutable incident records with actor/action timeline.
  - Add explicit operator action states for triage lifecycle.
- Target files:
  - `backend/app/services/run_worker.py`
  - `backend/app/services/dpdp.py`
  - `backend/app/api/dpdp.py`
- API/event impact:
  - Add lifecycle fields for incidents: `state`, `opened_at`, `updated_at`, `resolution_notes`.
- Acceptance criteria:
  - Every quarantine event has a persisted immutable incident record.
  - Incident list API supports filtering by state and date range.
  - No secrets/sensitive raw text are emitted in logs/events.

## T5 - QA/Guardrails observability package

- Priority: P1
- Problem:
  - Need measurable quality operations for release-gate confidence.
- Scope:
  - Emit metrics and structured logs for:
    - qa iteration count
    - remediation success rate
    - guardrail fail gate distribution
    - gate7 quarantine rate
- Target files:
  - `backend/app/services/qa.py`
  - `backend/app/services/guardrails.py`
  - `backend/app/services/run_worker.py`
  - `backend/app/api/models.py` or observability route module if centralizing
- Acceptance criteria:
  - Metrics are queryable from existing observability surfaces.
  - Failures are traceable by `project_id` and `run_id`.
  - Logging excludes sensitive payloads.

## T6 - Contract and regression tests for Priority 1

- Priority: P0
- Problem:
  - Hardening changes need explicit regression protection.
- Scope:
  - Add tests for deterministic fallback gates, QA remediation loop, and gate7 quarantine path.
- Target files:
  - `backend/app/tests/test_runs.py`
  - `backend/app/tests/test_guardrails.py` (create if absent)
  - `backend/app/tests/test_dpdp.py` (create if absent)
  - `backend/app/tests/test_qa.py` (create if absent)
- Acceptance criteria:
  - Local-mode guardrails no longer always pass.
  - QA remediation path is exercised with failing then corrected output.
  - DPDP quarantine produces breach report and failed run status.

## Suggested delivery sequence

1. T1 local-mode guardrail deterministic checks  
2. T2 QA corrective loop wiring  
3. T6 tests for T1/T2 behaviors  
4. T3 DPDP detector confidence model  
5. T4 quarantine governance fields and APIs  
6. T5 observability integration + final regression pass

## Definition of done (Priority 1)

- Guardrails are no longer permissive in local mode.
- QA can issue and apply bounded corrective remediation.
- DPDP gate7 decisions include confidence/provenance and auditable quarantine lifecycle.
- Tests cover all critical failure/success paths.
