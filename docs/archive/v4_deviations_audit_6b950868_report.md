## ProcessDocStudio v4 — Deviations Audit Report

Source specs:
- `ProcessDocStudio_v4_Final.md`
- `README.md` (root)

Audit scope (per the v4 spec):
- Backend core pipeline (Coordinator/QA/Guardrails/DPDP, runs, SSE timeline)
- Frontend surfaces (Run Studio, SSE stream, draw.io collaboration, admin pages)

### Legend
- `Implemented`: present with behavior close to spec
- `Stubbed`: present but incomplete/placeholder logic
- `Missing`: not found in codebase
- `Behavior differs`: present but does not match the v4 requirement

---

## Section 4 — Architecture Deep Dive (major deviations)

1. **No LangGraph / Cowork-style agent orchestration**
   - Status: Missing
   - Evidence: `backend/app/agents/coordinator.py` is a straightforward orchestration wrapper; repo-wide search finds no `langgraph` usage.
   - Impact: v4’s “tool loop + stategraph coordinator” design is not realized; the lifecycle is not Cowork-modeled.

2. **No tool registry with tool-looped agents**
   - Status: Missing
   - Evidence: `backend/config/skill_registry.json` lists tools like `retrieve_context`, `web_search`, but the runtime does not implement and call them as agent tools.
   - Impact: required tool-loop behavior and tool-level governance are absent.

3. **`web_search` is entirely missing**
   - Status: Missing
   - Evidence: no `web_search` implementation under `backend/app/`; `backend/app/services/qa.py` scores outputs but performs no web-based fact verification.
   - Impact: v4 requirement (real-time web_search integrated throughout agents + mandatory QA verification) is not met.

4. **Tiered Context Assembly is not BM25/MMR (no retrieval engine)**
   - Status: Behavior differs
   - Evidence: `backend/app/services/retrieval.py` slices strings (`tier0[:2000]`, `tier1[:12000]`, `tier2[:10000]`) and concatenates; no BM25/MMR, no multi-query expansion, no deduplication strategy, no SHA-256 parse cache.
   - Impact: “project-specific context grounding” is not implemented as specified.

5. **Leading Practice (OneDrive/Graph) integration is not implemented**
   - Status: Missing
   - Evidence:
     - No OneDrive/Graph API code under `backend/app/`.
     - Frontend LP browser is a stub: `frontend/app/admin/lp-library/page.tsx`.
     - No `/api/lp-library` router group in `backend/app/api/routes.py`.
   - Impact: LP snippets retrieval, tagging/classification, and traceability do not exist.

6. **QA Agent Loop does not match the spec (no correction loop-back)**
   - Status: Behavior differs
   - Evidence:
     - `backend/app/services/qa.py` returns a single pass/fail style score; no 6-step QA review; no retrieval cross-check; no web_search verification; no loop-back to subagents.
     - `backend/app/agents/coordinator.py` always proceeds to guardrails after generating outputs.
   - Impact: v4’s QA loop (max 2 iterations, correction instructions to subagents) is not implemented.

7. **7-Gate Guardrail Pipeline is stubbed**
   - Status: Behavior differs / Stubbed
   - Evidence: `backend/app/services/guardrails.py` hard-codes gates 1–6 to `"pass"`; only Gate 7 depends on a boolean.
   - Impact: most guardrail gates are non-functional.

8. **DPDP Gate 7 quarantine + breach workflow are not implemented**
   - Status: Missing / Stubbed
   - Evidence:
     - `backend/app/services/dpdp.py` always returns `gate7_pass: True` after regex redaction.
     - `backend/app/agents/coordinator.py` passes `dpdp_gate7=state.get("dpdp_flags", {}).get("enabled", True)` (unconditionally true in worker).
     - No breach notification clock / DPO email workflow in codebase.
   - Impact: v4’s critical regulatory Gate 7 quarantine behavior is not present.

9. **Style & Brand engine is missing**
   - Status: Missing
   - Evidence: `backend/app/core/state.py` includes `style_profile`, but no enforcement in subagents or guardrails (guardrails gates 3/6 are hard-coded pass).
   - Impact: brand compliance and writing style controls are not enforced.

10. **Custom skills end-to-end management is stubbed**
   - Status: Stubbed / Missing
   - Evidence:
     - Admin UI is a stub: `frontend/app/admin/skills/page.tsx`.
     - Skills API is stubbed: `backend/app/api/skills.py` returns `items: []` and fixed `"custom-1"`.
     - Coordinator does not load or apply custom skill cards to determine tools/output schemas.
   - Impact: v4 custom skills upload/versioning/governance is not delivered.

11. **Output format registry is underutilized**
   - Status: Behavior differs
   - Evidence:
     - `backend/config/output_types.json` contains only narrative/raci entries.
     - Frontend hard-codes output types during run creation: `frontend/app/projects/[pid]/page.tsx` uses `output_types: ["narrative"]`.
     - Coordinator uses only a small static mapping in `_OUTPUT_AGENTS` and does not select formats/templates dynamically.
   - Impact: “no hardcoded formats” and UI-driven output selection spec is not satisfied.

12. **Persistence/artifact contract differs from spec**
   - Status: Behavior differs
   - Evidence:
     - `backend/app/api/run_artifacts.py` reads `drawio_xml.txt`, `narrative_md.md`, `dpdp_report_json.json`, etc.
     - Spec expects standardized filenames/structures like `drawio.xml`, `dpdp_report.json`, `qa_report.json`, `guardrail_report.json`.
   - Impact: consumers expecting v4 artifact names/paths may break; manifest/write semantics differ.

13. **SSE event types are narrower than spec**
   - Status: Behavior differs / Stubbed
   - Evidence:
     - `frontend/lib/types.ts` includes `output_chunk`, but backend never emits it.
     - Backend emits `plan_ready`, `step`, `qa_report`, `guardrail_event`, `done`/`failed` only.
   - Impact: the typed SSE stream contract in v4 is not fully met.

---

## Section 5 — Feature Specifications (high-level gaps)

1. **Web Search + QA fact verification**
   - Status: Missing
   - Evidence: no `web_search` tool; QA does not call external sources.

2. **Enhanced LP browsing + retrieval controls**
   - Status: Missing / Stubbed
   - Evidence: LP admin page is a static placeholder; no retrieval endpoints.

3. **Plugin architecture, marketplace, sandboxing**
   - Status: Missing
   - Evidence: no plugin configuration/execution system detected.

4. **Analytical modeling engine + Excel integration**
   - Status: Missing
   - Evidence: no model/excel services/endpoints found.

---

## Section 6 — API Surface Deviations

1. **Missing API groups required by the spec**
   - Status: Missing
   - Evidence: `backend/app/api/routes.py` only includes:
     - `/api/auth`, `/api/projects`, `/api/documents`, `/api/runs`, `/api/runs` artifacts, `/api/drawio`, `/api/workspace/{pid}/skills`, `/api/dpdp`.
   - Spec requires additional groups like `/api/lp-library` and `/api/workspace/{pid}/output-types`.

2. **Documents upload does not parse/classify**
   - Status: Behavior differs
   - Evidence: `backend/app/api/documents.py` reads bytes, computes sha256, writes to `workspace/.../source_docs/`; no parsing/chunking/tagging.

3. **DPDP workflows are partial placeholders**
   - Status: Stubbed
   - Evidence:
     - Consent endpoints exist, but DPDP engine redaction and Gate 7 quarantine/breach workflows are not complete.
     - Rights request returns `"queued"` without queue persistence/fulfillment.

---

## Reconciliation with `README.md` “Current Status”

- Where it matches:
  - End-to-end local run flow exists: auth -> create project -> create run -> HITL approval -> background execution -> persisted SSE timeline via `run_events`.
  - SSE reconnect/poll fallback exists in `frontend/app/projects/[pid]/runs/[rid]/page.tsx`.
  - draw.io collaboration exists via WebSocket lock/update mechanism.

- Where it diverges (notably):
  - `README.md` claims BM25/MMR + OneDrive Graph LP integration, but backend implements only truncation-based context.
  - `README.md` implies Gate 7 is driven by DPDP redaction; the current `DPDPService` always yields `gate7_pass: True`, so quarantine logic is absent.
  - `README.md` implies custom skills/DPDP compliance/better QA/guardrails upgraded placeholders; code shows admin/API stubs for skills and largely deterministic pass-through for guardrails gates 1–6.

---

## If you want next

I can generate a **Must/Should/Could/Won’t compliance matrix** (from spec Section 8) mapping each requirement to current implementation status with the same evidence pointers.

