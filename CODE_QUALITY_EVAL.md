# Code Quality Eval — Process Doc v2

> Generated: 2026-05-10 (automated daily review)  
> Scope: `backend/app/` — all Python source excluding `.venv/` and `__pycache__/`

---

## Eval Criteria

Each criterion is scored on a 1–5 scale: **1 = critical / widespread**, **5 = exemplary**.

| # | Criterion | Weight | Score | Finding |
|---|-----------|--------|-------|---------|
| E1 | Error handling specificity | High | 2 | 267 bare `except Exception:` blocks across 15 files |
| E2 | Database transaction safety | High | 2 | 74 bare `db.commit()` with no surrounding try/except |
| E3 | Resource cleanup reliability | Medium | 3 | 3 `shutil.rmtree(ignore_errors=True)` silently eating failures |
| E4 | Portability (no hardcoded paths) | High | 1 | 2 hardcoded `/Users/pallavchaturvedi/...` paths in production code |
| E5 | Logging hygiene | Medium | 3 | 3 `print()` statements in production code; `config.py` uses stderr |
| E6 | Test coverage breadth | High | 2 | 13 of 18 API route modules have zero test files |
| E7 | Test assertion density | Medium | 3 | Avg 1.8 asserts/test; security tests average only 0.8 |
| E8 | Code modularity | Medium | 2 | `projects.py` is 4206 lines; `coordinator.py` is 2518 lines |
| E9 | Async correctness | Medium | 4 | Async patterns used correctly; MCP bridge has 3 known sync TODOs |
| E10 | SSRF protection | High | 4 | `safe_get` wrapper present; `web_search.py` correctly calls external APIs only |

**Overall weighted score: 2.6 / 5.0**

---

## Score Breakdown

### E1 — Error Handling (Score: 2/5)

**Problem:** 267 bare `except Exception:` handlers across the codebase. Many silently swallow errors with no log.

**Top offenders (by count):**

| File | Count |
|------|-------|
| `api/projects.py` | 35 |
| `agents/subagents.py` | 28 |
| `services/run_worker.py` | 18 |
| `api/runs.py` | 13 |
| `agents/coordinator.py` | 12 |

**Pattern to fix:**
```python
# Before (swallows any error silently)
try:
    result = do_something()
except Exception:
    result = fallback_value

# After (log + re-raise or specific exception)
try:
    result = do_something()
except SomeSpecificError as e:
    _log.warning("do_something failed: %s", e)
    result = fallback_value
```

Note: Some `except Exception` handlers have `# noqa: S110` annotations marking them as intentional best-effort catches — those are acceptable. The remaining unmarked ones should be audited.

---

### E2 — Database Transaction Safety (Score: 2/5)

**Problem:** 74 `db.commit()` calls without a `try/except` guard. If any commit fails mid-operation, the database is left in a partially-written state.

**Highest-risk locations:**
- `api/projects.py:2540-2569` — cascade delete with 11 sequential `db.execute()` calls before a single commit
- `api/runs.py` — 16 commits across various run lifecycle operations
- `api/tasks.py` — 6 commits across task CRUD operations

**Pattern to fix:**
```python
# Before
db.execute(delete(...))
db.execute(delete(...))
db.commit()

# After
try:
    db.execute(delete(...))
    db.execute(delete(...))
    db.commit()
except Exception:
    db.rollback()
    raise HTTPException(status_code=500, detail="Operation failed")
```

---

### E3 — Resource Cleanup (Score: 3/5)

**Problem:** 3 locations use `shutil.rmtree(path, ignore_errors=True)`, which silently ignores permission errors, symlink attacks, and mid-delete failures.

**Locations:**
- `api/projects.py:2569` — project workspace deletion
- `api/runs.py:687` — run directory cleanup  
- `api/runs.py:711` — run directory cleanup (cancel path)

**Fix:** Log failures explicitly so ops can detect cleanup debt:
```python
try:
    shutil.rmtree(run_dir)
except OSError as e:
    _log.error("Failed to delete run dir %s: %s", run_dir, e)
    # Don't raise — cleanup failure shouldn't fail the API response
```

---

### E4 — Hardcoded Paths (Score: 1/5)

**Problem:** Two production source files contain absolute paths tied to a single developer's machine.

```
backend/app/agents/subagents.py:51
backend/app/api/runs.py:44
```

Both assign:
```python
_DEBUG_LOG_PATH = Path("/Users/pallavchaturvedi/Agentic Projects/Process Doc v2/.cursor/debug-a9841a.log")
```

This code will silently fail or write to the wrong place on any other machine (CI, staging, Docker).

**Fix:**
```python
_DEBUG_LOG_PATH = Path(os.getenv("DEBUG_LOG_PATH", "")).expanduser() or None
```

---

### E5 — Logging Hygiene (Score: 3/5)

**Problem:** `backend/app/core/config.py:24-27` uses `print(..., file=sys.stderr)` for debug output on startup. `backend/app/agents/teammate_main.py:110` uses `print(json.dumps(...))` for structured output.

**Fix for config.py:**
```python
log = logging.getLogger(__name__)
log.debug("Using .env files: %s", env_files)
```

The `teammate_main.py` print may be intentional (stdout protocol output) — verify before changing.

---

### E6 — Test Coverage Breadth (Score: 2/5)

**13 of 18 API route modules have zero test coverage:**

```
agent_bash, dpdp, drawio_collab, formats, lp_library,
model_realtime_ws, models, routes, run_artifacts,
runs, skills, swarm, tasks
```

Notably **`runs`** (1691 lines, core workflow) and **`tasks`** have no tests. These are the most business-critical paths.

**Recommended priority order:**
1. `runs` — most complex, highest traffic
2. `tasks` — CRUD + scheduling
3. `swarm` — multi-agent orchestration
4. `skills` — user-facing execution

---

### E7 — Test Assertion Density (Score: 3/5)

Most test files have low assertion counts, meaning tests exercise code paths without fully verifying behavior.

| File | Tests | Asserts | Ratio |
|------|-------|---------|-------|
| `test_phase1_security.py` | 10 | 8 | 0.8 |
| `test_end_to_end_regeneration.py` | 1 | 1 | 1.0 |
| `test_token_budgets.py` | 12 | 17 | 1.4 |

Security tests averaging <1 assertion per test is a red flag — they may be testing execution rather than outcomes.

---

### E8 — Code Modularity (Score: 2/5)

**God files detected:**

| File | Lines | Concern |
|------|-------|---------|
| `api/projects.py` | 4206 | 70+ routes, CRUD + AI + wiki + brands + cascade delete |
| `agents/coordinator.py` | 2518 | Orchestration logic for all agent types |
| `api/runs.py` | 1691 | Run lifecycle + streaming + controls |

`projects.py` in particular is a monolith. It mixes project CRUD, project settings, AI generation triggers, wiki management, brand configuration, and cascade deletion in one file. This makes it hard to test, navigate, or change safely.

**Suggested splits for `projects.py`:**
- `api/projects_core.py` — CRUD, settings, membership
- `api/projects_ai.py` — generation triggers
- `api/projects_wiki.py` — wiki-related routes
- `api/projects_brands.py` — brand configuration

---

### E9 — Async Correctness (Score: 4/5)

Async patterns are generally correct. Timeouts use `asyncio.wait_for`. File reads use `await file.read()`. DB calls are synchronous (expected for SQLite/SQLAlchemy sync sessions).

**Known open item:** MCP bridge (`services/mcp/bridge.py:60,70`, `services/mcp/registry.py:117`) has 3 TODO comments about upgrading to async stdio streams. These are blocking calls in async contexts but are marked as known technical debt.

---

### E10 — SSRF Protection (Score: 4/5)

`safe_get` in `services/http_fetch.py` provides URL validation, IP allowlist enforcement, redirect validation, and byte limits. `web_search.py` uses `httpx.Client` but only calls known external provider APIs (Brave, Tavily, Google) — not user-supplied URLs — so SSRF risk is low.

---

## Top 5 Recommended Actions (by impact/effort ratio)

### Action 1: Fix hardcoded paths (30 min, Critical)

Files: `backend/app/agents/subagents.py:51`, `backend/app/api/runs.py:44`

Replace the hardcoded `_DEBUG_LOG_PATH` with an env-var-backed path or remove debug logging entirely if it's no longer used.

---

### Action 2: Replace `print()` with logging in `config.py` (15 min, Medium)

File: `backend/app/core/config.py:24-27`

Use `log.debug()` instead of `print(..., file=sys.stderr)`.

---

### Action 3: Audit top 20 bare `except Exception:` handlers (4 hours, High)

Start with `api/projects.py` (35 occurrences). For each:
- If it's intentional best-effort, add `# noqa: S110` with a comment explaining why
- If it's swallowing real errors, narrow the exception type and add logging

---

### Action 4: Add transaction guards to cascade-delete path (2 hours, High)

File: `backend/app/api/projects.py:2540-2569`

Wrap the cascade delete sequence in `try/except/rollback`. This is the highest-risk single location: 11 sequential deletes before a single commit.

---

### Action 5: Add basic smoke tests for `runs` and `tasks` APIs (1 day, High)

Start with happy-path tests for the most common operations:
- `POST /runs` — create a run
- `GET /runs/{id}` — fetch run status
- `POST /tasks` — create a task
- `GET /tasks` — list tasks

Even simple integration tests catching 4xx/5xx regressions add significant value.

---

## Eval Rerun Checklist

To measure progress on the next eval run:

```bash
# Count bare excepts (target: reduce by 50% in 2 weeks)
grep -rn "except Exception:" backend/app/ --include="*.py" | grep -v ".venv" | wc -l

# Check for hardcoded paths (target: 0)
grep -rn "pallavchaturvedi\|/Users/" backend/app/ --include="*.py" | grep -v ".venv" | grep -v test_ | wc -l

# Count print statements in prod code (target: 0)
grep -rn "^\s*print(" backend/app/ --include="*.py" | grep -v ".venv" | grep -v test_ | wc -l

# Test file count vs route file count (target: >50% coverage)
ls backend/tests/test_*.py | wc -l
ls backend/app/api/*.py | wc -l
```
