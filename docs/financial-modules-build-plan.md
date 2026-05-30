# Financial Analysis Modules — Build Plan

Six frontend components are fully built but disconnected. Three require only frontend wiring; three require new backend endpoints first. Grouped into four phases by dependency order.

---

## Components inventory

| Component | File | Backend needed? | Status |
|-----------|------|-----------------|--------|
| FinancialModelWizard | `frontend/components/models/FinancialModelWizard.tsx` | No — uses existing `POST /models` | Wire only |
| EnhancedConflictResolution | `frontend/components/excel/EnhancedConflictResolution.tsx` | Partial — needs history + impact fields added to existing conflict endpoint | Extend existing |
| AuditLogViewer | `frontend/components/excel/AuditLogViewer.tsx` | Yes — expose `audit_log.jsonl` via API | New endpoint |
| ConsolidatedFinancialDashboard | `frontend/components/models/ConsolidatedFinancialDashboard.tsx` | Yes — compute consolidated metrics from spreadsheet data | New endpoint |
| FinancialReportGenerator | `frontend/components/models/FinancialReportGenerator.tsx` | Yes — generate/export XLSX, PDF, PNG | New endpoint |
| CollaborativeEditingLocks | `frontend/components/excel/CollaborativeEditingLocks.tsx` | Yes — real-time lock state, user presence | New endpoint + WebSocket |

---

## Phase 1 — Wire FinancialModelWizard (no backend work)

**Goal:** Replace the bare model creation form on the models list page with the full wizard.

**What exists:**
- `frontend/app/projects/[pid]/models/page.tsx` — lists models, has a simple inline create form
- `useCreateModel(projectId)` hook in `frontend/hooks/useModels.ts` — accepts `{ name, template, assumptions }`, calls `POST /api/projects/{pid}/models`
- `FinancialModelWizard` — its `onComplete(data: ModelData)` callback receives `{ name, template, assumptions }`

**Changes:**
1. In `models/page.tsx`, import `FinancialModelWizard` and replace the inline create form with it.
2. Pass `onComplete` wired to `useCreateModel().mutate({ name: data.name, ...data.assumptions })`.
3. On success, close the wizard and invalidate the models list query.

**Verification:** Navigate to `/projects/{pid}/models`, click create, step through the wizard, confirm the model appears in the list.

---

## Phase 2 — AuditLogViewer + EnhancedConflictResolution

These two can be built in parallel since they share the same backend area (conflict/event infrastructure).

### 2a. AuditLogViewer

**Backend work:**
- `backend/app/api/models.py` — add `GET /projects/{pid}/models/{mid}/excel/audit-log`
- Reads `workspace/{pid}/models/{mid}/excel/conflicts/audit_log.jsonl` (already written on conflict events)
- Returns `{ events: AuditEvent[] }` with fields the component expects: `id`, `timestamp`, `eventType`, `user`, `modelId`, `cellRef`, `oldValue`, `newValue`, `metadata`, `severity`
- Map existing log fields to the component's `EventType` union: `model_created`, `model_updated`, `conflict_detected`, `conflict_resolved`, `assumption_changed`, `sync_completed`, `external_data_synced`, `budget_recorded`
- Implement a query parameter `?limit=200&offset=0` for pagination; default last 200 events

**Frontend work:**
- Add `useAuditLog(projectId, modelId)` hook in `useModels.ts` querying the new endpoint
- Mount `AuditLogViewer` in a new "Audit" tab on `models/[mid]/page.tsx`; pass `events` from the hook
- Wire `onExport` to trigger `window.open` / download for CSV and JSON; PDF export can remain as a `console.warn("PDF export not yet implemented")` stub

### 2b. EnhancedConflictResolution

**What exists:**
- `GET /projects/{pid}/models/{mid}/excel/conflicts` returns `ModelConflict[]` but without `history` or `impact` fields
- `ConflictResolutionPanel` is live and uses the existing hook — keep it, do not remove it

**Backend work:**
- Extend `GET /projects/{pid}/models/{mid}/excel/conflicts/{cid}` to include:
  - `history: CellVersion[]` — pull from `audit_log.jsonl` filtered by `cellRef`
  - `impact: { dependentCells, affectedModels, impactCount }` — can be computed statically from the model's formula dependency graph (or return an empty object if graph isn't available yet)

**Frontend work:**
- Extend `useModelConflicts` to also expose a `useConflictDetail(projectId, modelId, conflictId)` hook that fetches the enriched single-conflict response
- Add `EnhancedConflictResolution` as the content of a new "Advanced" mode toggle inside `models/[mid]/conflicts/page.tsx` — keeping `ConflictResolutionPanel` as the default view
- Wire `onResolve` to `useResolveModelConflict`, `onBatchResolve` to a new `useBatchResolveConflicts` mutation that calls the existing resolve endpoint in a loop

---

## Phase 3 — ConsolidatedFinancialDashboard

**Goal:** Surface computed financial metrics (profitability, liquidity, leverage, growth), income statement, variance, and forecast in a single dashboard tab.

**Backend work:**
- Add `GET /projects/{pid}/models/{mid}/financial/consolidated` to `backend/app/api/models.py`
- Implementation in a new `backend/app/services/financial_metrics.py`:
  - Load the model's active scenario assumptions (`grossMargin`, `operatingMargin`, `taxRate`, etc.)
  - Derive the metric groups from assumptions + existing dashboard KPI data (`GET /dashboard` already returns `kpis`)
  - Return shaped response matching the component's prop types: `{ metrics: FinancialMetrics, statements: FinancialStatement, variances: VarianceData[], forecasts: ForecastData[], assumptions: Record<string, number> }`
  - For `statements` and `variances`, this requires actual actuals data — return empty arrays if no actuals exist yet, and document that
  - For `forecasts`, return a simple linear projection from the base assumptions for 3–5 years

**Frontend work:**
- Add `useConsolidatedFinancial(projectId, modelId)` hook in `useModels.ts`
- Mount `ConsolidatedFinancialDashboard` in a new "Financial Overview" tab on `models/[mid]/page.tsx`
- Pass all props from the hook response; missing optional props (variances, forecasts) degrade gracefully since all are `?` in the component

---

## Phase 4 — FinancialReportGenerator + CollaborativeEditingLocks

These are the most backend-heavy and can be started in parallel after Phases 1–3 are stable.

### 4a. FinancialReportGenerator

**Backend work:**
- Add `POST /projects/{pid}/models/{mid}/reports/generate` to `backend/app/api/models.py`
- Request body: `{ reportType, format, title, includeCharts, includeTables, recipients }`
- Implementation in `backend/app/services/report_generator.py`:
  - `xlsx`: Use `openpyxl` to produce a multi-sheet workbook (statements, variance, assumptions)
  - `pdf`: Use `weasyprint` or `reportlab`; or produce HTML and return it for browser print
  - `png`: Return chart images generated with `matplotlib`
  - Write output to `workspace/{pid}/models/{mid}/reports/{timestamp}_{title}.{ext}` and return a signed download URL or base64 blob
  - Email delivery (`recipients` field): if set, call the existing email utility if one exists, else log a warning and skip
- For MVP, XLSX is the most valuable format — deliver it first; PDF and PNG can be stubbed with `{"status": "not_yet_implemented"}`

**Frontend work:**
- Add `useGenerateReport(projectId, modelId)` mutation hook
- Mount `FinancialReportGenerator` in a new "Reports" tab on `models/[mid]/page.tsx`
- Wire `onGenerate` to the mutation; set `isLoading` from mutation state
- On success, trigger `window.open(data.download_url)` or decode and download the base64 blob

### 4b. CollaborativeEditingLocks

This component requires real-time data (cell locks, user presence, version conflicts) that does not exist in the backend yet.

**Backend work:**
- Add a lock store to `backend/app/services/excel_lock_service.py`:
  - In-memory dict keyed by `(project_id, model_id, cell_ref)` for local dev
  - Redis-backed for multi-replica (behind `CACHE_ALLOW_MEMORY_FALLBACK`)
- Add WebSocket endpoint `WS /ws/models/{pid}/{mid}/collab` in `backend/app/api/models.py`:
  - On connect: broadcast current lock state + presence list
  - On message `{"action": "lock", "cellRef": "B4"}`: acquire lock, broadcast to others
  - On message `{"action": "release", "cellRef": "B4"}`: release lock, broadcast
  - On disconnect: release all locks held by that session, broadcast updated presence
- Add REST fallback `GET /projects/{pid}/models/{mid}/collaborative/locks` for polling when WebSocket is unavailable

**Frontend work:**
- Add `useCollaborativeLocks(projectId, modelId)` hook using a `useEffect`-managed WebSocket with polling fallback (similar pattern to `useModelRealtime`)
- Mount `CollaborativeEditingLocks` in a new "Collaboration" tab on `models/[mid]/page.tsx`
- Wire `onRetry` to send `{"action": "lock", "cellRef": ...}` on the WebSocket
- Wire `onForceRelease` to a new `useForceReleaseLock` mutation (Owner role only) calling `DELETE /projects/{pid}/models/{mid}/collaborative/locks/{cellRef}`

---

## Tab layout on models/[mid]/page.tsx after all phases

Current tabs: (none — single page view)

Proposed tab bar:
```
Overview | Financial Overview | Conflict Resolution | Advanced Conflicts | Audit | Reports | Collaboration
```

- **Overview** — existing `ModelDashboard` + `ExcelIntegrationPanel` + `StyleProfileForm`
- **Financial Overview** — `ConsolidatedFinancialDashboard` (Phase 3)
- **Conflict Resolution** — existing `ConflictResolutionPanel` (unchanged)
- **Advanced Conflicts** — `EnhancedConflictResolution` (Phase 2b)
- **Audit** — `AuditLogViewer` (Phase 2a)
- **Reports** — `FinancialReportGenerator` (Phase 4a)
- **Collaboration** — `CollaborativeEditingLocks` (Phase 4b)

---

## Dependency graph

```
Phase 1 (wizard)  ──────────────────────────────────────────► ship immediately

Phase 2a (audit)  ── new backend endpoint ──────────────────► ~1 day backend + 0.5 day frontend
Phase 2b (enh conflict) ── extend existing endpoint ────────► ~0.5 day backend + 0.5 day frontend

Phase 3 (dashboard) ── new metrics service ─────────────────► ~1.5 days backend + 0.5 day frontend

Phase 4a (reports) ── new report generation service ────────► ~2 days backend + 0.5 day frontend
Phase 4b (collab locks) ── new WebSocket + lock store ──────► ~3 days backend + 1 day frontend
```

Total estimate: ~10 backend-days, ~3.5 frontend-days, deliverable in 4 focused sprints.
