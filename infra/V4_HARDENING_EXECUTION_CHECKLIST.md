# v4 Hardening Execution Checklist

Purpose: convert the strict v4 hardening requirements into an implementation sequence that can be executed and validated end-to-end.

Status legend:
- `[ ]` not started
- `[~]` in progress
- `[x]` complete
- `[!]` blocked

## Priority Plan

- **P0 (release-blocking):**
  - True XLSX parser + schema inference + parse quality gates
  - Bidirectional OneDrive/SharePoint sync engine with checkpoint resume
  - Per-cell conflict detection + resolution APIs + audit log
  - WebSocket model/dashboard live update pipeline (+ replay/fallback)
- **P1 (stabilization):**
  - Performance tuning, background worker resilience, observability SLO dashboards
  - Security/governance hardening for channels and sync actions
- **P2 (operational excellence):**
  - Runbooks, chaos/failure drills, backfill migrations, operator tooling

## Stream A - XLSX Parse/Metrics + Schema Inference (P0)

### A1. Backend parser foundations
- [x] Add workbook parser service (`backend/app/services/xlsx_parser.py`) with:
  - sheet iteration, cell coordinates, formula/value/type extraction
  - named ranges, merged cells, table/range metadata capture
  - parse lineage model (`source_file`, `sheet`, `a1_ref`, parser timestamp)
- [~] Add parse domain models (`backend/app/models/modeling.py` or equivalent):
  - `WorkbookSnapshot`, `SheetSnapshot`, `CellSnapshot`, `SchemaInferenceResult`
- [x] Persist parse snapshot artifacts under:
  - `workspace/{pid}/models/{mid}/excel/snapshots/{snapshot_id}.json`

### A2. Schema inference engine
- [x] Implement inference service (`backend/app/services/schema_inference.py`):
  - semantic type inference (`number`, `percent`, `currency`, `date`, etc.)
  - role inference (`dimension`, `measure`, `assumption`, `derived`, etc.)
  - confidence score + ambiguity reason fields
- [~] Infer and persist units/currency/periodicity hints.
- [ ] Mark protected/computed cells for writeback policy enforcement.

### A3. Quality metrics + API contract
- [x] Extend import endpoint (`/excel/import`) response with:
  - parse metrics (`cell_coverage`, `formula_coverage`, `typed_cell_ratio`, `schema_confidence_mean`, warnings count)
  - structured diagnostics by sheet/range/cell
- [x] Enforce threshold gate with `422` on low-quality parse.
- [x] Add parse drift endpoint:
  - `GET /api/projects/{pid}/models/{mid}/excel/schema-diff?from=<snapshot>&to=<snapshot>`

### A4. Tests
- [ ] Unit tests: parser edge cases (merged cells, date serials, formulas, named ranges).
- [x] Integration tests: import known workbook fixture and verify stable schema output.
- [ ] Regression fixtures: "wide sparse sheet", "formula-heavy financial model", "mixed locale formats".

## Stream B - OneDrive/SharePoint Bidirectional Sync Loop (P0)

### B1. Graph integration + sync primitives
- [~] Add Graph client service (`backend/app/services/graph_sync.py`) with:
  - delta query pull support
  - idempotent push updates with request id keys
  - etag/revision handling
- [x] Store sync checkpoints in:
  - `workspace/{pid}/models/{mid}/excel/sync/checkpoint.json`
  - fields: `delta_token`, `last_remote_revision`, `last_applied_change_id`, timestamps
- [x] Build `cell_ref_map` persistence:
  - `workspace/{pid}/models/{mid}/excel/sync/cell_ref_map.json`

### B2. Sync job orchestration
- [~] Add scheduler/worker loop (poll/webhook trigger capable).
- [x] Apply remote deltas -> normalized changes -> local model updates.
- [x] Push accepted local updates -> remote workbook with retry-safe semantics.
- [x] Add bounded retry + exponential backoff + dead-letter queue for permanent failures.

### B3. Sync APIs + state model
- [x] Add/extend endpoints:
  - `POST /api/projects/{pid}/models/{mid}/excel/sync/start`
  - `POST /api/projects/{pid}/models/{mid}/excel/sync/stop`
  - `GET /api/projects/{pid}/models/{mid}/excel/sync/status`
  - `POST /api/projects/{pid}/models/{mid}/excel/sync/replay-dead-letter/{item_id}`
- [x] Standardize sync states:
  - `idle`, `syncing`, `degraded`, `conflicted`, `failed`

### B4. Tests
- [x] Integration tests with mocked Graph delta pages and etag collisions.
- [x] Resume test: worker restart continues from checkpoint with no duplicated apply.
- [x] Idempotency test: duplicate push request id does not double-write.

## Stream C - Conflict Resolution (Per Cell) (P0)

### C1. Conflict detection model
- [x] Implement three-way compare service:
  - base revision + local candidate + remote candidate
- [x] Emit conflict record with class:
  - `value_mismatch`, `type_mismatch`, `formula_changed`, `deleted_range`, `structural_shift`
- [x] Persist conflict records:
  - `workspace/{pid}/models/{mid}/excel/conflicts/{conflict_id}.json`

### C2. Conflict APIs
- [x] Add endpoints:
  - `GET /api/projects/{pid}/models/{mid}/excel/conflicts`
  - `GET /api/projects/{pid}/models/{mid}/excel/conflicts/{cid}`
  - `POST /api/projects/{pid}/models/{mid}/excel/conflicts/{cid}/resolve`
  - `POST /api/projects/{pid}/models/{mid}/excel/conflicts/{cid}/reopen`
- [x] Resolve payload must support:
  - chosen side (`local`/`remote`/`policy`)
  - optional rationale
  - actor identity (from auth context)

### C3. Frontend conflict UI
- [x] Create conflict center route:
  - `frontend/app/projects/[pid]/models/[mid]/conflicts/page.tsx`
- [x] Add per-cell tri-view diff (`base`, `local`, `remote`) with type/formula badges.
- [~] Add queue filters (sheet/severity/owner) and bulk policy resolve.
- [~] Require explicit confirmation for formula/type/structural conflicts.

### C4. Audit/event linkage
- [x] Persist immutable decision audit records (actor, timestamp, policy, rationale).
- [~] Emit timeline events for conflict detected/resolved/reopened.
- [x] Prevent sync finalize while unresolved high-risk conflicts exist.

### C5. Tests
- [~] Frontend tests for diff rendering, filtering, and resolve actions.
- [x] API tests for auth, validation, and immutable audit behavior.
- [~] End-to-end test: conflict appears after remote edit, resolved in UI, writeback resumes.

## Stream D - WebSocket Live Model/Dashboard Updates (P0)

### D1. Realtime backend channel
- [x] Add WebSocket endpoint (project/model scoped auth):
  - `/api/ws/projects/{pid}/models/{mid}`
- [x] Implement subscription manager with tenant isolation.
- [x] Define typed event envelope:
  - `event_id`, `event_type`, `project_id`, `model_id`, `payload`, `server_ts`
- [x] Persist event stream for replay:
  - `workspace/{pid}/models/{mid}/events/index.jsonl` or DB equivalent

### D2. Event producers
- [~] Emit events from:
  - model updates/version snapshots
  - scenario recomputes
  - sync state transitions
  - conflict lifecycle changes
  - dashboard KPI refreshes
- [x] Ensure monotonic event IDs and deterministic ordering per model channel.

### D3. Frontend realtime integration
- [x] Add client realtime layer (`frontend/lib/realtime.ts`) with reconnect/backoff.
- [x] Track connection state (`connected`, `reconnecting`, `degraded`) in store.
- [~] Incrementally patch charts/tables/cards without full reload.
- [x] Implement gap recovery:
  - on reconnect call replay API with `last_event_id`
- [x] Keep fallback compatibility with SSE/polling using same event schema.

### D4. Tests
- [ ] Backend tests for auth isolation and replay ordering.
- [ ] Frontend tests for reconnect and stale-data indicators.
- [ ] Load test for concurrent websocket sessions and event throughput.

## Cross-Cutting Work (P1)

### Observability
- [ ] Add metrics:
  - `sync_loop_lag_ms`
  - `sync_retry_count`
  - `conflict_open_total`
  - `ws_active_sessions`
  - `ws_event_delivery_lag_ms`
- [ ] Add tracing spans across import -> inference -> sync -> conflict -> dashboard update.
- [ ] Add health probes for sync worker and websocket hub.

### Security & Governance
- [ ] Enforce per-project/model authorization checks for all sync/conflict/ws routes.
- [ ] Ensure tokens/secrets never persist in artifacts or frontend logs.
- [ ] Keep audit logs append-only with tamper-evident metadata.

### Data Migration & Backward Compatibility
- [ ] Add migrations for new sync/conflict/event schemas.
- [ ] Backfill existing model workspaces with default metadata/checkpoint files.
- [ ] Keep old dashboard fetch path operational during phased websocket rollout.

## Release Gates (Definition of Done)

### Gate 1 - Functional correctness
- [ ] XLSX parse preserves formulas/types across fixture set.
- [ ] Sync loop converges on local/remote concurrent edit scenarios.
- [ ] Conflict UI resolves per-cell conflicts with audit trail.
- [ ] Dashboard receives live updates without manual refresh.

### Gate 2 - Reliability
- [ ] Restart-safe resume validated for parser/sync/realtime workers.
- [ ] Network/Graph transient faults recover via retry/backoff.
- [ ] Dead-letter replay succeeds for supported failure classes.

### Gate 3 - Performance
- [ ] p95 change-to-UI latency <= 2s on staging workload.
- [ ] No unbounded memory growth in websocket and sync workers.
- [ ] Reconcile throughput meets target for representative workbook size.

### Gate 4 - Security/compliance
- [ ] Authz penetration tests for project/model channel boundaries pass.
- [ ] Conflict/sync audit logs are immutable and queryable.
- [ ] Secret scanning confirms no credential leakage in logs/artifacts.

## Suggested Execution Order (Two-week sprint framing)

- **Sprint slice 1 (days 1-3):**
  - A1, A2 foundations + B1 primitives + D1 event envelope
- **Sprint slice 2 (days 4-6):**
  - A3 quality gates + B2 loop orchestration + C1/C2 conflict backend
- **Sprint slice 3 (days 7-9):**
  - C3 UI + D3 frontend realtime + B3 status APIs
- **Sprint slice 4 (days 10-12):**
  - D2 event producers + C4 audit linkage + cross-cutting observability/security
- **Sprint slice 5 (days 13-14):**
  - End-to-end validation, bug fixes, release gate signoff

## Immediate Next Actions

- [ ] Confirm backend storage target for event/conflict/sync records (DB vs workspace files) and lock schema.
- [ ] Decide sync trigger mode for initial rollout (polling only vs polling + webhook).
- [ ] Create initial PR stack:
  - PR1 parser/inference foundations
  - PR2 sync engine + checkpoint model
  - PR3 conflict APIs + UI
  - PR4 websocket channel + dashboard live updates
