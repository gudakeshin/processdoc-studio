# ProcessDocStudio v4 Re-baseline and Reconciliation (Step 1)

Date: 2026-03-26  
Scope: Reconcile current code state against `README.md` and `v4_deviations_audit_6b950868_report.md`.

## 1) Reconciled Status Matrix (v4-critical areas)

| Area | Classification | Current state | Evidence |
|---|---|---|---|
| API group `/api/workspace/{pid}/output-types` | Implemented baseline | Router mounted and backed by output-types API + registry config. | `backend/app/api/routes.py`, `backend/app/api/formats.py`, `backend/config/output_types.json` |
| API group `/api/lp-library` | Implemented baseline | Search/refresh/bookmarks endpoints present and mounted. | `backend/app/api/routes.py`, `backend/app/api/lp_library.py` |
| Model + Excel API surface | Implemented baseline | Model CRUD/scenarios/versions/dashboard and excel import/export/sync/conflicts/events endpoints exist. | `backend/app/api/models.py`, `backend/app/api/routes.py` |
| Frontend output-type selection | Implemented baseline | Uses format registry hook and validates selected format IDs before run creation. | `frontend/app/projects/[pid]/page.tsx` |
| Run Studio SSE handling | Implemented baseline | Handles `plan_ready`, `step`, `output_chunk`, `qa_report`, `guardrail_event`, `done`, `failed`. | `frontend/hooks/useRunStream.ts` |
| Model realtime WS + replay | Implemented baseline | WebSocket reconnect and gap replay via events endpoint. | `frontend/hooks/useModelRealtime.ts`, `frontend/lib/realtime.ts` |
| Conflict-resolution UI (per-cell) | Implemented baseline | Per-cell diff UI with resolve/reopen actions is present. | `frontend/components/excel/ConflictResolutionPanel.tsx` |
| `web_search` capability | Implemented baseline | Service implemented with Brave + Google fallback, cache/rate controls; used by QA. | `backend/app/services/web_search.py`, `backend/app/services/qa.py` |
| Retrieval quality engine | Hardening gap | BM25/MMR exists, but retrieval tool-loop integration and production retrieval depth are incomplete. | `backend/app/services/retrieval.py`, `backend/app/services/tool_registry.py` |
| LP Graph ingestion (OneDrive/SharePoint) | Hardening gap | LP feature runs in local index mode; enterprise Graph ingestion for LP remains pending. | `backend/app/services/leading_practices.py` |
| QA correction loop | Hardening gap | Iterative scoring exists, but correction/rewrite feedback loop to subagents is limited. | `backend/app/services/qa.py`, `backend/app/agents/coordinator.py` |
| Guardrail strictness (gates 1-6) | Hardening gap | Gate framework exists; local mode remains permissive pass-by-default when Claude is disabled. | `backend/app/services/guardrails.py` |
| DPDP maturity | Hardening gap | Gate 7 and quarantine path exist; detection is regex-level and needs stronger compliance depth. | `backend/app/services/dpdp.py`, `backend/app/services/run_worker.py` |
| LangGraph/stategraph cowork orchestration | Spec-missing | No LangGraph/stategraph orchestration found; current orchestration is custom coordinator flow. | `backend/app/agents/coordinator.py` |
| Plugin marketplace/sandbox architecture | Spec-missing | No plugin marketplace/sandbox execution system found. | Repo-wide feature absence; no plugin runtime modules |

## 2) Contradiction Log (README vs prior audit)

Priority is based on planning impact (high to medium).

1. API groups reported missing in audit but implemented now.  
   - Contradiction: audit marked `/api/lp-library` and `/api/workspace/{pid}/output-types` as missing.  
   - Reconciled truth: both groups are implemented and mounted.
2. Modeling + Excel reported missing in audit but implemented now.  
   - Contradiction: audit flagged analytical modeling/Excel as missing.  
   - Reconciled truth: broad model/excel API surface exists.
3. `web_search` reported missing in audit but implemented now.  
   - Contradiction: audit stated no `web_search`.  
   - Reconciled truth: implemented service and QA integration exist.
4. LP integration framing mismatch.  
   - Contradiction: README can be read as capability present; audit says missing.  
   - Reconciled truth: local LP index/search is implemented; Graph-backed LP ingestion remains pending.
5. DPDP Gate 7 mismatch.  
   - Contradiction: audit implied always-pass behavior.  
   - Reconciled truth: gate7/quarantine path exists; hardening gap is detection/compliance depth, not absence.
6. Retrieval mismatch.  
   - Contradiction: audit said no BM25/MMR; README roadmap says BM25/MMR future work.  
   - Reconciled truth: BM25/MMR baseline exists; production-grade retrieval/tool-loop depth remains pending.
7. Guardrail maturity overstated if read as strict enforcement.  
   - Contradiction: framework exists vs strict behavior expectation.  
   - Reconciled truth: framework is present; strictness depends on Claude-enabled path and needs hardening.
8. Custom skills status mixed.  
   - Contradiction: “stubbed only” vs “fully delivered”.  
   - Reconciled truth: base CRUD/admin is present; deeper runtime governance and rollout behavior remain to harden.

## 3) Step 2 Backlog (risk-ordered)

### Priority 1 - QA/Guardrails/DPDP hardening quality
- Implement deterministic minimum checks for gates 1-6 when Claude is disabled (no blanket pass defaults).
- Add QA correction loop that feeds explicit remediation instructions back into output generation.
- Strengthen DPDP from regex-only toward higher-confidence detection/pseudonymization and auditable consent/rights workflows.

### Priority 2 - Retrieval + LP enterprise wiring
- Wire retrieval tool usage end-to-end so QA and generation paths use non-placeholder retrieval outputs.
- Improve retrieval quality controls (query expansion, dedup, ranking diagnostics, traceability).
- Implement Graph-backed LP ingestion/sync for OneDrive/SharePoint while retaining local fallback.

### Priority 3 - Governance/observability/security hardening
- Add run/model-level observability for event lag, retry counts, conflict rates, and websocket health.
- Harden token lifecycle controls (refresh rotation/revocation) and auditability around privileged actions.
- Enforce acceptance gates in CI/release checks (functional/non-functional/security criteria from README strict section).

## 4) Exit Criteria Check (Step 1)

- Reconciled labels applied for all v4-critical areas: `Implemented baseline`, `Hardening gap`, `Spec-missing`.  
- Contradictions from prior audit are explicitly resolved to current code truth.  
- Step 2 backlog is dependency-aware and risk-ordered.
