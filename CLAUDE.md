# Process Doc v2 — agent onboarding

Use this file as the front door; everything else is detail in-tree.

## Read first

- **`README.md`** — runbooks, Cowork-style architecture summary, and where features live.
- **`ARCHITECTURE.md`** — layered design, data flow, and integration points.
- **`DOCUMENTATION_INDEX.md`** — index of longer design/ops notes (`infra/`, `docs/`).

## Local configuration

Application settings load from repo-root **`.env`** (and optional `backend/.env`). **`JWT_SECRET`** must be a strong value (≥16 characters, not a placeholder); validation is in `backend/app/core/config.py`. After a fresh clone, generate and append one:

```bash
make dev.secret
```

The **`pytest`** suite under `backend/tests/` sets `JWT_SECRET` via `backend/tests/conftest.py` so CI and local test runs do not need a real `.env`.

## Code map (high signal)

| Area | Location |
|------|----------|
| FastAPI app & middleware | `backend/app/main.py` |
| Auth helpers | `backend/app/core/auth.py` |
| Wiki HTTP API | `backend/app/api/wiki.py` (all routes require auth; project wikis enforce `require_project_role`) |
| Wiki ingest / refresh | `backend/app/services/wiki_ingest.py`, `wiki_refresh.py` |
| SSRF-safe HTTP GET | `backend/app/services/http_fetch.py` (`safe_get`) |
| Office zip safety | `backend/app/core/office/zip_safety.py` |
| Deliverables | `backend/app/core/deliverable_*.py` |
| Frontend wiki UI | `frontend/components/wiki/` |

## Repository hygiene

Treat **`processdoc.db`**, the entire **`workspace/`** tree, Office lock files (`~$*`), and stray generated **`.pptx` / `.docx`** at the repo root as machine-local. They are ignored from git via the root **`.gitignore`**. Historical status write-ups live under **`docs/archive/`**; keep the root clean (README, ARCHITECTURE, this file, TOKEN_BUDGET_IMPLEMENTATION, DOCUMENTATION_INDEX).

## Remediation roadmap

Cross-cutting work (security hardening, PPTX/XLSX/DOCX quality, observability, module splits) is tracked as a **phased program** (Phase 0 hygiene → Phase 1 security criticals → parallel doc-quality and DX tracks). When implementing, align with existing utilities: `get_current_user` / `require_project_role`, `BrandingContext` / `branding_service`, `otel_tracing` / `langfuse_tracing`, `run_budget` / `token_budgets`, and `zip_safety` for any new zip paths.
