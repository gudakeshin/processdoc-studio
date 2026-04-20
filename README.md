# ProcessDoc Studio

AI-native process documentation platform. Upload source documents, describe your deliverables in chat, approve the plan, and ProcessDoc executes a multi-agent pipeline that produces RACI matrices, SOPs, process maps, narratives, DOCX/PPTX/XLSX/PDF — all with human-in-the-loop approval gates and a full audit trail.

**Local-first:** run everything on your machine with Python and Node. PostgreSQL, Redis, and Docker are optional.

### Repository hygiene

The following paths are **machine-local** and must not be committed: `processdoc.db`, the entire `workspace/` tree (per-project uploads, parsed JSON, runs, wiki mirrors), Office lock files such as `~$*.pptx`, and stray generated `.pptx`/`.docx` at the repo root. They are ignored via the root `.gitignore`. After cloning, start the backend once (or run Alembic migrations) so SQLite or Postgres creates a fresh database; project workspaces are created automatically under `workspace/` when you use the app.

---

## Architecture

ProcessDoc Studio is built on the **Cowork architecture pattern** — the same design principles that underpin Anthropic's Cowork product. The system is structured around four layers, implemented in four phases:

### Phase 1: LLM-Reasoned Coordinator (Extended Thinking)
The coordinator can call `claude_generate_with_thinking()` in `claude.py` (budget from `anthropic_thinking_budget_tokens`) to produce a structured **execution plan** before workers run. Planning is toggled with `coordinator_llm_planning_enabled` and intersects with user-requested outputs so scope cannot expand silently. When planning succeeds, `run_worker` persists a **`coordinator_plan`** (or `execution_plan`) run event; **Zone C** (`ZoneCLiveMonitor.tsx`) renders rationale, planned-output chips, optional **thinking excerpt**, per-output notes, and fallback metadata. If the API is off or JSON is invalid, dispatch falls back to the existing canonical ordering.

### Phase 2: Iterative Sub-agent Tool Loop
Deliverable sub-agents use **`run_subagent_tool_loop()`** in `claude_tools.py`: Anthropic **custom tools** built from `tool_registry.py` (`tool_to_anthropic_schema` / `anthropic_tool_definitions`, `resolve_tool_call`, `tool_names_for_skill`, `default_tools_for_output_type`). Rounds and token ceilings come from **`subagent_tool_max_rounds`** and **`subagent_tool_max_tokens`**. Skill frontmatter `tools` lists are filtered to registered names (including aliases such as **`memory_lookup`**). The separate **`run_claude_tools_loop()`** path remains for the guarded **Bash / Text Editor** HTTP API (`agent_bash.py`), which still uses Anthropic built-in bash and text-editor tools. Mid-run **`agent_tool_round`** events carry agent id, round, and tool trace for the audit trail.

### Phase 3: Sub-agent Context Isolation
`AgentContext` and `AgentOutput` live in **`backend/app/agents/agent_types.py`**. The coordinator builds a context per output type (`build_agent_context`), runs `(ctx) -> AgentOutput` workers, and merges with **`merge_agent_output`**. Workers receive an optional **`emit_event`** closure wired from the run worker (same session as other run events) instead of mutating a shared dict inside the agent.

### Phase 4: MCP Tool Protocol (scaffold + integration)
**`backend/app/services/mcp/`** provides JSON-RPC-style helpers (`protocol.py`), subprocess **lifecycle** for entries in **`backend/config/mcp_servers.json`** (`registry.py`), and **`try_mcp_tool_call`** / **`call_mcp_tool`** (`bridge.py`) over stdio. **`resolve_tool_call()`** tries the native registry first, then running MCP servers. Server startup on API boot is gated by **`mcp_enabled`** (default off); config path is fixed relative to the backend package (`config/mcp_servers.json`). Stdio I/O still uses synchronous pipes with room for async hardening—treat MCP as **integration-ready** for connectors you install and enable, not a guarantee of every edge case in the field.

---

## Run Studio UI (Cowork-Inspired Layout)

The Run Studio page follows the Cowork two-column conversation cockpit pattern:

```
┌──────────────────────────────────────────┬──────────────────────┐
│ Left column — Run Conversation            │ Right panel          │
│                                           │                      │
│  [Instruction Chat]                       │  Activity            │
│  [Coordinator plan + reasoning (Zone C)]  │  ├─ Coordinator      │
│  [Execution Audit Trail]                  │  ├─ narrative_agent  │
│  [Output Review]                          │  │   retrieve_context│
│  [Collaborative process map]              │  │   web_search      │
│                                           │  ├─ raci_agent       │
│  ────────────────────────────────────     │  └─ sop_agent        │
│  ╔════ APPROVAL BANNER (sticky) ════╗    │                      │
│  ║ Plan ready — approve to execute  ║    │  Artifacts  Context  │
│  ╚══════════════════════════════════╝    │                      │
└──────────────────────────────────────────┴──────────────────────┘
```

**Key UI principles (mirroring Cowork):**

- **Approval gate is a persistent banner, not a modal.** `ApprovalBanner` sits sticky at the bottom of the conversation column and handles all three approval checkpoints in one component: plan approval (`plan_ready`), mid-run HITL gates, and final review (`review_ready`).
- **Tool activity is separated from the conversation.** `ToolActivityFeed` (right panel) shows live skill execution groups with nested tool call rows, animated running indicators, and status badges. The conversation column shows decisions and outputs; the activity panel shows what's happening underneath.
- **The UI is a read-only view of server state.** The SSE stream is the IPC bus. The run worker owns the state machine (`pending → running → approval_required → running → done`). The frontend never drives execution — it reflects state and emits approval signals.
- **Coordinator plan in Zone C.** Decisions (and Live) show `coordinator_plan` / `execution_plan` with rationale text, planned outputs, scrollable reasoning excerpt when present, and optional per-output notes—instead of truncating the payload to three keys.
- **Governance and reliability are visible in context.** Permission pipeline stages, retry/recovery mode, hook outcomes, heartbeat, and replay continuity are surfaced as explicit user-facing semantics in Run Studio.

---

## Recent Developments

### ADD-001 v6 hardening (2026-04)

- **Admission-time permission pipeline:** `POST /api/runs` now executes automated permission stages before approval/execution and can create runs in `plan_blocked` with stage/reason metadata in events.
- **Plan-aware stage-6 checks:** policy evaluation now inspects plan payload structure (`run_contract.nodes` / contract completeness signals), not only output types.
- **Externalized policy bundle support:** permission pipeline can load policy bundle overrides from `POLICY_BUNDLE_PATH`, while emitting `policy_version`, `rule_id`, `policy_hash`, and `enforcement_mode`.
- **Retry mode formalization:** retry scheduling now distinguishes `fast_retry` vs `cooldown_retry`, with thresholds driven by config.
- **Durable hook governance controls:** hook disable actions are persisted (`hook_controls` table, Alembic `011_hook_controls`) with actor/reason metadata; workers sync disabled hooks from DB.
- **Strict event contract toggle:** canonical run-event envelope remains fixed (`schema_version`, `event_type`, `phase`, `ts_ms`, `run_id`, `payload`) and legacy payload flattening is controlled by `EVENT_CONTRACT_STRICT`.

### ADD-001 UI hardening (2026-04)

- **`plan_blocked` first-class UX:** Run Studio now represents blocked preflight outcomes explicitly instead of presenting all runs as approvable.
- **Approval banner expansion:** unified banner supports blocked-state remediation (`Re-run preflight`) in addition to `plan_ready`, `hitl_gate`, and `review_ready`.
- **Audit timeline semantics:** event rendering now explicitly humanizes `permission_stage`, `hook_result`, `run_control_applied`, `recovery_mode`, and `heartbeat`.
- **Governance tab in Activity panel:** operators can run permission simulation and inspect/disable hooks directly from the UI.
- **Replay continuity messaging:** Run page and Studio now show continuity hints when stream falls back to poll/replay mode.

### ADD-001 v5 stabilization (2026-04)

- Durable run control fields (`pause_requested`, `resume_requested`, `abort_requested`) and hook execution ledger (`hook_executions`) introduced via migration `010_run_controls_and_hook_execution`.
- Typed run-event schema and canonical envelope with `schema_version=run-events-v1`.
- Hook visibility and emergency disable endpoints added for runtime operations.

### Earlier 2026-03 updates

#### MCP tool protocol (backend)

- **`backend/app/services/mcp/protocol.py`** — JSON-RPC request/response helpers for MCP-style `tools/call` over line-oriented stdio
- **`backend/app/services/mcp/registry.py`** — Load **`backend/config/mcp_servers.json`**, spawn servers when **`mcp_enabled`** is true, shutdown on app exit; **`${VAR}`** env interpolation in server config
- **`backend/app/services/mcp/bridge.py`** — `try_mcp_tool_call` / `call_mcp_tool` with timeouts and broken-pipe handling (stdio layering still has TODOs for full async)
- **`tool_registry.resolve_tool_call()`** — Native **`TOOL_REGISTRY`** first, then MCP; **`ValueError`** if unknown
- **`main.py` lifespan** — `startup_mcp_servers()` / `shutdown_mcp_servers()` alongside the run worker
- **Tests** — **`test_mcp_*.py`** (73 tests) plus broader backend suite (**182** collected tests under `app/tests/`)
- **`backend/config/mcp_servers.json`** — live config file (often `[]`); copy patterns from **`mcp_servers_example.json`**

#### Phase 1 UI: coordinator plan in Zone C

- **`ZoneCLiveMonitor.tsx`** — Dedicated **`CoordinatorPlanEventBody`** for `coordinator_plan` / `execution_plan`: rationale as body text, output chips, coordinator reasoning panel for **`thinking_excerpt`**, metadata line, collapsible per-output notes, fallback messaging when the LLM planner is not used

#### Run Studio UI Redesign (Cowork Layout)

- **`ApprovalBanner.tsx`** — Unified sticky approval gate replacing three scattered UI patterns (ZoneBPlanReview, inline approvalHint in ZoneA, floating final-approve button). Single amber banner handles `plan_ready`, `hitl_gate`, and `review_ready` states.
- **`ToolActivityFeed.tsx`** — New right panel with Activity / Artifacts / Downloads / Context tabs. Shows live skill groups, nested tool call rows, and animated running indicators. Replaces the static Context Inspector sidebar.
- **`ZoneAInstruction.tsx`** — Simplified: `approvalHint` prop removed (approval moved to unified banner).
- **`RunStudio.tsx`** — Restructured from 2-column to conversation-column + tool-feed layout. Grid changed to `xl:grid-cols-[minmax(0,1fr)_360px]`. Left column uses `relative flex flex-col` so the sticky banner adheres to the column, not the viewport. ~355 lines of Context Inspector JSX removed.

#### Operations, scale, and security (2026-03)

- **[`infra/OPERATIONS.md`](infra/OPERATIONS.md)** — concurrency definitions for “500 users” (HTTP sessions vs long-lived SSE/WebSocket vs concurrent agent runs), soak/SLO gates, rollout checklist
- **[`infra/PRODUCTION_TOPOLOGY.md`](infra/PRODUCTION_TOPOLOGY.md)** — Postgres connection pool tuning (`DATABASE_POOL_*`), Redis queue/workers, `CACHE_ALLOW_MEMORY_FALLBACK`, Uvicorn/Gunicorn, reverse-proxy timeouts for SSE/WebSocket
- **[`infra/load/README.md`](infra/load/README.md)** — `rest_burst.py` (concurrent `/health`), `sse_stream_smoke.py` (concurrent SSE opens), `soak_500_runs.py`, `slo_gate.py`
- **[`infra/SECURITY.md`](infra/SECURITY.md)** — secrets, CORS/JWT-in-URL/`localStorage` guidance, agent tools, CI scanning
- **CI:** `pip-audit` (backend), `npm audit --audit-level=high` (frontend), **[`.github/dependabot.yml`](.github/dependabot.yml)** for Actions/pip/npm weekly updates

#### Feature updates (2026-03)

- User-defined output-type routing end-to-end (docx, pptx, xlsx, pdf, brand_guidelines)
- Extended skill registry with v2 cards (narrative_v2, raci_v2, sop_v2, process_map_v2)
- Binary artifact generation (output.docx, output.pptx, output.xlsx, output.pdf) with base64 API payloads
- Chat-first output planning with hash-validated plan confirmation
- Run lifecycle with explicit review and gated quality steps
- Strict visual QA gate (image-based, Claude vision)
- Optional Bash tool and Text Editor tool (guarded, sandboxed)
- RACI XLSX default and delivery
- Analytical modeling: model CRUD, scenarios, version snapshots, Excel import/export/sync
- XLSX hardening: real workbook parsing, schema inference, parse quality metrics
- Bidirectional sync foundations: delta tokens, dead-letter queue, idempotent replay
- Conflict lifecycle: per-cell classification, resolve/reopen APIs, immutable audit log
- Realtime model channels: authenticated WebSocket, persisted event stream with replay

---

## Local Development (No Docker)

### Prerequisites

- Python 3.11+
- Node.js 18+

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Create `backend/.env` (FastAPI loads this file from the backend root on startup):

```bash
cp ../.env.example .env
# Required for non-dev: JWT_SECRET (min 16 chars when PROCESSDOC_ENV is staging/production)
# Common: WORKSPACE_ROOT, ANTHROPIC_API_KEY, coordinator / sub-agent / MCP flags (see Environment Variables Reference)
```

You can also keep a repo-root `.env` for your own tooling; the API process reads **`backend/.env`** via `main.py`.

**Database:** Omit `DATABASE_URL` to use SQLite at `backend/processdoc.db` — tables created on startup. For an existing DB, run `alembic upgrade head` in `backend/` to include the latest ADD-001 revisions (including `010_run_controls_and_hook_execution` and `011_hook_controls`).

**Redis:** Used for shared parse/search cache and (when `RUN_QUEUE_BACKEND=redis`) the run queue. If Redis is unreachable, the API falls back to an **in-process** cache per process and logs a warning—fine for single-node dev; for **multiple API replicas** set `CACHE_ALLOW_MEMORY_FALLBACK=false` so startup fails without Redis (see [`infra/PRODUCTION_TOPOLOGY.md`](infra/PRODUCTION_TOPOLOGY.md)).

Start the API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### 2. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # optional: API_PROXY_TARGET if FastAPI is not on 127.0.0.1:8000
npm run dev
```

Open [http://localhost:3000](http://localhost:3000), sign in, create a project, iterate with Run Assistant chat, confirm plan, and continue in Run Studio.

CORS: `CORS_ORIGINS` lists explicit allowed browser origins. In **`development`** (not staging/production), the API also allows a **regex** for common dev URLs (localhost, `127.0.0.1`, `::1`, and private LAN IPs on any port) so `fetch` works when you open the app as `http://192.168.x.x:3000` or similar.

**Development default:** the UI calls **same-origin** `/api/*`; Next.js proxies to FastAPI (`API_PROXY_TARGET`, default `http://127.0.0.1:8000`), so the browser does not open a separate connection to `:8000`. Set `NEXT_PUBLIC_API_URL` only for a remote API, or `NEXT_PUBLIC_API_DIRECT=true` to force the browser to use `http://localhost:8000` directly.

Override explicit origins with `CORS_ORIGINS` (comma-separated) when needed.

### 3. First Run Flow

1. `POST /api/auth/login` with `{"email":"you@example.com","password":"yourpassword"}` — first login creates the user
2. `POST /api/projects` — create a project
3. `POST /api/projects/{pid}/conversation/messages` — iterate and review `decision_prompts`
4. `POST /api/projects/{pid}/conversation/decisions` — submit selected options until unresolved prompts are cleared
5. `POST /api/projects/{pid}/conversation/confirm` — confirm the latest plan hash
6. `POST /api/runs` — run starts in `plan_ready` or `plan_blocked` (if automated permission preflight fails)
7. Optional: `POST /api/runs/{pid}/permission/simulate` — dry-run permission stages before approval
8. `POST /api/runs/{pid}/{rid}/approve` — HITL gate: approve execution start (for `plan_ready` runs)
9. `GET /api/runs/{pid}/{rid}/stream` — execution events stream via SSE
10. When `review_ready`: inspect outputs, then `POST /api/runs/{pid}/{rid}/final-approve` to run guardrails

---

## MCP Tool Integration

External tools are wired via JSON config — no code changes required.

### 1. Install an MCP connector

```bash
# Example: OneDrive
npm install -g @anthropic/mcp-onedrive
```

### 2. Set credentials

```bash
export ONEDRIVE_CLIENT_ID="your-client-id"
export ONEDRIVE_CLIENT_SECRET="your-secret"
export ONEDRIVE_TENANT_ID="your-tenant-id"
```

### 3. Configure `backend/config/mcp_servers.json`

Edit the JSON array in **`backend/config/mcp_servers.json`** (create it if missing, or start from the example file):

```json
[
  {
    "id": "onedrive",
    "command": "npx",
    "args": ["-y", "@anthropic/mcp-onedrive"],
    "env": {
      "ONEDRIVE_CLIENT_ID": "${ONEDRIVE_CLIENT_ID}",
      "ONEDRIVE_CLIENT_SECRET": "${ONEDRIVE_CLIENT_SECRET}",
      "ONEDRIVE_TENANT_ID": "${ONEDRIVE_TENANT_ID}"
    }
  }
]
```

See **`backend/config/mcp_servers_example.json`** for Slack and local test server templates.

### 4. Enable MCP in the API process

Set in `backend/.env` (or environment):

```bash
MCP_ENABLED=true
```

If `MCP_ENABLED` is false (default), subprocesses are not started; native tools still work.

### 5. Tools available automatically

```python
from app.services.tool_registry import resolve_tool_call

# Resolves: native registry first, then MCP servers, then raises ValueError
result = resolve_tool_call("list_files", {"path": "/"}, {"project_id": "proj-1"})
```

### Tool resolution order

1. **Native registry** — Python callables in `TOOL_REGISTRY` (zero overhead)
2. **MCP servers** — JSON-RPC 2.0 over stdio, first server that responds wins
3. **Error** — `ValueError("Unknown tool: ...")`

### Environment variables for MCP

| Variable | Purpose |
|----------|---------|
| `MCP_ENABLED` | When `true`, load **`backend/config/mcp_servers.json`** and spawn configured servers at API startup |

There is no separate `MCP_SERVERS_CONFIG` setting; the path is fixed to **`backend/config/mcp_servers.json`** relative to the backend package layout.

---

## Optional: PostgreSQL, Redis, Docker

### PostgreSQL (local)

```bash
export DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost:5432/processdoc"
# Optional: tune SQLAlchemy pool (non-SQLite only); align with Uvicorn workers vs Postgres max_connections
# export DATABASE_POOL_SIZE=5
# export DATABASE_MAX_OVERFLOW=10
# export DATABASE_POOL_PRE_PING=true
cd backend && alembic upgrade head && uvicorn app.main:app --reload --port 8000
```

For multi-user production, prefer Postgres over SQLite. Full deployment notes (pool sizing, Redis, workers, nginx timeouts): [`infra/PRODUCTION_TOPOLOGY.md`](infra/PRODUCTION_TOPOLOGY.md).

### Redis (local)

```bash
export REDIS_URL="redis://localhost:6379/0"
# Optional: distributed run-queue mode
export RUN_QUEUE_BACKEND="redis"
export RUN_EXECUTION_QUEUE_NAME="processdoc:run-execution"
export RUN_MAX_ACTIVE_GLOBAL="500"
export RUN_MAX_ACTIVE_PER_PROJECT="20"
export RUN_MAX_ACTIVE_PER_USER="8"
```

Start a dedicated worker:

```bash
cd backend && python -m app.workers.run_execution_worker
```

Worker health: `GET /workers/health`, `GET /metrics`, `GET /admission/{project_id}`

### Docker (optional)

`docker-compose.yml` is provided for Postgres + Redis via containers. Not required for the SQLite + in-memory cache path. It does **not** run the API—use your own process manager or platform for Uvicorn/Gunicorn in production.

### draw.io self-hosted editor (optional)

```bash
docker-compose up -d drawio
# Configure: NEXT_PUBLIC_DRAWIO_BASE_URL (default https://localhost:8444)
```

Accept the self-signed cert by visiting `https://localhost:8444` once.

---

## Scale, load testing, and “500 concurrent users”

**Define what you mean by concurrent:** idle logged-in users, open **SSE** (`/stream`) / **WebSocket** tabs, or **active agent runs**—each stresses different limits (workers, DB pool, LLM quotas). See the table in [`infra/OPERATIONS.md`](infra/OPERATIONS.md).

| Concern | Summary |
|--------|---------|
| **Data + queue** | Postgres + tuned `DATABASE_POOL_*`; `RUN_QUEUE_BACKEND=redis` with **separate worker processes** when running multiple API replicas |
| **Cache** | Redis for shared cache; `CACHE_ALLOW_MEMORY_FALLBACK=false` in multi-replica prod to avoid split-brain in-memory caches |
| **Long-lived connections** | Raise reverse-proxy **read timeouts** and disable buffering for SSE; see nginx example in [`infra/PRODUCTION_TOPOLOGY.md`](infra/PRODUCTION_TOPOLOGY.md) |
| **Backpressure** | `RUN_MAX_ACTIVE_GLOBAL`, `RUN_MAX_ACTIVE_PER_PROJECT`, `RUN_MAX_ACTIVE_PER_USER` cap **runs**, not raw HTTP concurrency; see `GET /admission/{project_id}` on the API (not under `/api`) |

**Load harnesses** (require a running API; see [`infra/load/README.md`](infra/load/README.md)):

```bash
# Burst GET /health (no auth)
BASE_URL=http://localhost:8000 CONCURRENCY=200 python infra/load/rest_burst.py

# Concurrent short-lived SSE connections (JWT access token + existing run)
BASE_URL=http://localhost:8000 AUTH_TOKEN=... PROJECT_ID=... RUN_ID=... \
  CONCURRENT_STREAMS=100 python infra/load/sse_stream_smoke.py

# 500-user run lifecycle soak + SLO gate (documented in infra/OPERATIONS.md)
BASE_URL=http://localhost:8000 AUTH_TOKEN=... PROJECT_ID=... \
  CONCURRENCY_USERS=500 python infra/load/soak_500_runs.py > infra/load/last_soak_report.json
python infra/load/slo_gate.py --soak-report infra/load/last_soak_report.json --metrics-url http://localhost:8000/metrics
```

---

## Security and dependency hygiene

- **Checklist and deployment guidance:** [`infra/SECURITY.md`](infra/SECURITY.md) (secrets, CORS, JWT in query strings for EventSource, `localStorage` / XSS, Bash/MCP).
- **Agent tools:** [`infra/bash_tool_security.md`](infra/bash_tool_security.md), [`infra/text_editor_tool_security.md`](infra/text_editor_tool_security.md).
- **Automated scanning:** GitHub Actions runs **`pip-audit`** (after upgrading pip/setuptools) and **`npm audit --audit-level=high`**; [**Dependabot**](.github/dependabot.yml) proposes weekly dependency updates for Actions, `backend/`, and `frontend/`.

---

## Optional: Anthropic Claude for Agentic Generation

Set `ANTHROPIC_API_KEY` to enable Claude-based generation. Falls back to deterministic local generation when not set.

```bash
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_CLAUDE_MODEL=claude-haiku-4-5   # default
ANTHROPIC_TEMPERATURE=0.2
ANTHROPIC_MAX_TOKENS=4096
```

Claude drives:
- Process extraction (build `ProcessModel`)
- Sub-agent generation: RACI, SOP, narrative, process map, DOCX, PPTX, XLSX, PDF (primary path: **`run_subagent_tool_loop`** with registry tools; deterministic fallbacks when Claude is off)
- Coordinator LLM planning when enabled (`coordinator_llm_planning_enabled`, `claude_generate_with_thinking()`)
- QA loop scoring and guardrail gate checks (Gates 1–6)

Optional tuning (see `backend/app/core/config.py` and `.env.example`):

```bash
COORDINATOR_LLM_PLANNING_ENABLED=true
ANTHROPIC_THINKING_BUDGET_TOKENS=8000
ANTHROPIC_COORDINATOR_PLAN_MAX_TOKENS=8192
SUBAGENT_TOOL_MAX_ROUNDS=5
SUBAGENT_TOOL_MAX_TOKENS=4096
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
INSTRUCTION_DECISION_PROMPTS_ENABLED=true
SCRATCHPAD_VISIBILITY_ENABLED=true
```

---

## Environment Variables Reference

```bash
# Core
PROCESSDOC_ENV=development            # staging/production enforce stronger JWT_SECRET
JWT_SECRET=required
WORKSPACE_ROOT=./workspace
DATABASE_URL=sqlite:///./processdoc.db   # or postgresql+psycopg://...
DATABASE_POOL_SIZE=5                   # non-SQLite only
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_PRE_PING=true
CACHE_ALLOW_MEMORY_FALLBACK=true      # false = require Redis (recommended multi-replica)
REDIS_URL=redis://localhost:6379/0

# Anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_CLAUDE_MODEL=claude-haiku-4-5
ANTHROPIC_TEMPERATURE=0.2
ANTHROPIC_MAX_TOKENS=4096
COORDINATOR_LLM_PLANNING_ENABLED=true
ANTHROPIC_THINKING_BUDGET_TOKENS=8000
ANTHROPIC_COORDINATOR_PLAN_MAX_TOKENS=8192
SUBAGENT_TOOL_MAX_ROUNDS=5
SUBAGENT_TOOL_MAX_TOKENS=4096

# Web search
BRAVE_SEARCH_API_KEY=
GOOGLE_CUSTOM_SEARCH_API_KEY=
GOOGLE_CUSTOM_SEARCH_CX=

# LP library
LP_LIBRARY_LOCAL_PATH=/path/to/lp-library

# Run queue (see ARCHITECTURE.md)
RUN_QUEUE_BACKEND=local             # or redis
RUN_EXECUTION_QUEUE_NAME=processdoc:run-execution
RUN_MAX_ACTIVE_GLOBAL=500
RUN_MAX_ACTIVE_PER_PROJECT=20
RUN_MAX_ACTIVE_PER_USER=8
RUN_WORKER_ID=worker-1
RUN_RETRY_INDEFINITE_FOR_SCHEDULED=false
RETRY_COOLDOWN_THRESHOLD_SEC=20.0

# ADD-001 policy/event governance
POLICY_EVALUATOR_VERSION=policy-v1
POLICY_CLASSIFIER_THRESHOLD=0.5
POLICY_ENFORCE_ENABLED=true
POLICY_BUNDLE_PATH=
EVENT_CONTRACT_STRICT=true

# Uploads
UPLOAD_MAX_BYTES=52428800

# Tool integrations
BASH_TOOL_ENABLED=false             # requires Owner/Editor role
TEXT_EDITOR_TOOL_ENABLED=false

# MCP (optional)
MCP_ENABLED=false                   # true: spawn servers from backend/config/mcp_servers.json

# CORS
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

---

## Tests

CI (on push/PR to `main`/`master`) runs backend **pytest**, **Alembic** Postgres smoke, **pip-audit**, frontend **lint**, **tests**, **Vitest**, **build**, and **npm audit**. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

```bash
# Backend (182 tests under app/tests/ at last collection)
cd backend
source .venv/bin/activate
pytest

# MCP-focused suites only (~73 tests)
pytest app/tests/test_mcp*.py -v

# Frontend type-check
cd frontend && npx tsc --noEmit

# Frontend build verification
cd frontend && npm run build
```

### MCP Test Coverage

| Suite | Tests | Status |
|---|---|---|
| `test_mcp_protocol.py` | 21 | ✅ |
| `test_mcp_registry.py` | 17 | ✅ |
| `test_mcp_bridge.py` | 13 | ✅ |
| `test_mcp_tool_resolution.py` | 11 | ✅ |
| `test_mcp_e2e_integration.py` | 11 | ✅ |
| **Total MCP** | **73** | **✅** |

---

## Project Layout

```
.
├── .env.example                        # Env template (copy to backend/.env for the API)
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── coordinator.py          # Run orchestration, planning hook, worker dispatch
│   │   │   ├── agent_types.py          # AgentContext / AgentOutput / merge helpers
│   │   │   └── subagents.py            # Deliverable agents (tool loop + fallbacks)
│   │   ├── api/                        # FastAPI routers (runs, projects, agent_bash, …)
│   │   ├── core/                       # Config, auth, middleware, exceptions
│   │   ├── db/                         # SQLAlchemy models and session
│   │   ├── services/
│   │   │   ├── mcp/
│   │   │   │   ├── protocol.py         # JSON-RPC helpers for MCP-style stdio messages
│   │   │   │   ├── registry.py         # MCP server lifecycle management
│   │   │   │   └── bridge.py           # Tool call routing to MCP servers
│   │   │   ├── tool_registry.py        # Native + MCP tool resolution
│   │   │   ├── claude.py               # Anthropic API wrapper (incl. extended thinking)
│   │   │   ├── claude_tools.py         # run_claude_tools_loop (bash/editor API); run_subagent_tool_loop
│   │   │   ├── run_worker.py           # Run state machine and SSE event emitter
│   │   │   ├── scheduled_tasks.py      # Cron-like recurring task scheduler
│   │   │   ├── web_search.py           # Brave/Google search integration
│   │   │   ├── leading_practices.py    # LP library retrieval
│   │   │   └── drawio_builder.py       # draw.io XML generation
│   │   ├── tests/                      # pytest (182 tests collected)
│   │   │   ├── test_mcp_protocol.py
│   │   │   ├── test_mcp_registry.py
│   │   │   ├── test_mcp_bridge.py
│   │   │   ├── test_mcp_tool_resolution.py
│   │   │   ├── test_mcp_e2e_integration.py
│   │   │   ├── test_coordinator_planning.py
│   │   │   └── test_tool_registry.py
│   │   └── main.py                     # FastAPI app with MCP lifespan hooks
│   ├── config/
│   │   ├── mcp_servers.json            # MCP server definitions (user-created)
│   │   ├── mcp_servers_example.json    # Reference templates (OneDrive, Slack, local)
│   │   ├── output_types.json           # Registered output format catalog
│   │   └── skills/                     # Skill cards (v2) with companion docs
│   ├── scripts/                        # e.g. mirror_anthropic_skills.py
│   ├── .env.example                    # Backend-focused env snippet (optional)
│   └── pyproject.toml
├── frontend/
│   ├── app/                            # Next.js App Router pages
│   │   └── projects/[pid]/runs/[rid]/  # Run Studio page
│   ├── components/
│   │   ├── RunStudio.tsx               # Main run orchestrator (Cowork layout)
│   │   └── run-studio/
│   │       ├── ApprovalBanner.tsx      # Unified sticky approval gate (NEW)
│   │       ├── ToolActivityFeed.tsx    # Live tool activity right panel (NEW)
│   │       ├── ZoneAInstruction.tsx    # Instruction chat
│   │       ├── ZoneCLiveMonitor.tsx    # Audit trail + coordinator_plan / agent_tool_round UI
│   │       └── ZoneDOutputReview.tsx   # Output preview
│   └── hooks/
│       └── useRunStream.ts             # SSE event subscription
├── .github/
│   ├── dependabot.yml                  # Weekly Actions / pip / npm updates
│   └── workflows/ci.yml                # pytest, alembic, pip-audit, npm audit, lint, build
├── infra/
│   ├── OPERATIONS.md                   # Concurrency definitions, soak/SLO gates
│   ├── PRODUCTION_TOPOLOGY.md          # Postgres pool, Redis, proxy, workers
│   ├── SECURITY.md                     # Ops security checklist + CI scanning
│   ├── load/                           # rest_burst, sse_stream_smoke, soak_500_runs, slo_gate
│   └── ...
└── README.md
```

---

## API Endpoints Reference

### Run lifecycle

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Authenticate, get JWT |
| `POST` | `/api/projects` | Create project |
| `POST` | `/api/projects/{pid}/conversation/messages` | Chat-based run planning |
| `POST` | `/api/projects/{pid}/conversation/decisions` | Submit structured plan decisions (single/multi-select prompts) |
| `POST` | `/api/projects/{pid}/conversation/confirm` | Confirm plan (hash-validated) |
| `POST` | `/api/runs` | Create run from confirmed plan |
| `POST` | `/api/runs/{pid}/permission/simulate` | Dry-run permission pipeline (supports enforce/dry-run and optional plan payload) |
| `POST` | `/api/runs/{pid}/{rid}/approve` | HITL gate: approve plan execution |
| `GET` | `/api/runs/{pid}/{rid}/stream` | SSE event stream |
| `GET` | `/api/runs/{pid}/{rid}/events?after_event_id={id}` | Hydrate / poll events |
| `GET` | `/api/runs/{pid}/{rid}/artifacts` | Fetch run artifacts + status |
| `PATCH` | `/api/runs/{pid}/{rid}/plan` | Edit plan before approval |
| `POST` | `/api/runs/{pid}/{rid}/final-approve` | Final review approval → guardrails |
| `POST` | `/api/runs/{pid}/{rid}/control` | `pause` / `resume` / `stop` |

Run Studio includes an operator-focused Governance tab in the right panel, powered by the permission simulation and hook governance endpoints.

### Workspace and skills

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/workspace/{pid}/output-types` | Registered output format catalog |
| `GET` | `/api/workspace/{pid}/skills` | Skill registry |
| `PUT` | `/api/workspace/{pid}/skills/{sid}` | Update skill card |
| `GET` | `/api/workspace/{pid}/skills/{sid}/companions` | Companion docs for skill |

### LP library

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/lp-library/search?project_id={pid}&q={query}` | Search LP library |
| `POST` | `/api/lp-library/refresh?project_id={pid}` | Rebuild LP index |
| `GET` | `/api/lp-library/bookmarks?project_id={pid}` | User bookmarks |

### Modeling and Excel sync

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/api/projects/{pid}/models` | Model CRUD |
| `POST` | `/api/projects/{pid}/models/{mid}/excel/import` | Import workbook |
| `POST` | `/api/projects/{pid}/models/{mid}/excel/sync` | Trigger sync |
| `GET` | `/api/projects/{pid}/models/{mid}/excel/conflicts` | List conflicts |
| `POST` | `/api/projects/{pid}/models/{mid}/excel/conflicts/{cid}/resolve` | Resolve conflict |
| `WS` | `/api/ws/projects/{pid}/models/{mid}?token={jwt}` | Realtime model channel |

### Observability

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/health/ready` | DB + Redis readiness |
| `GET` | `/api/health/visual-qa` | Visual QA dependency check |
| `GET` | `/metrics` | Full observability snapshot |
| `GET` | `/metrics/prometheus` | Prometheus text format |
| `GET` | `/workers/health` | Worker heartbeat summary |
| `GET` | `/admission/{pid}` | Active-run admission status |
| `GET` | `/api/runs/{pid}/hooks` | Hook registry visibility (source/order/idempotency/concurrency/disabled) |
| `POST` | `/api/runs/{pid}/hooks/disable` | Emergency hook disable by hook name |

### Project memory (environment)

These variables control how **Memory page** rows (`MemoryItem`), **memory events**, and **per-user preferences** feed `assembled_context`. See also [`backend/app/core/config.py`](backend/app/core/config.py) and [`.env.example`](.env.example).

| Variable | Default | Effect |
|---|---|---|
| `MEMORY_COMPACTION_V1_ENABLED` | `true` | Coordinator uses `assemble_v2` so memory events + profile + (when v2 retrieval is on) memory items shape context. |
| `MEMORY_V2_RETRIEVAL_ENABLED` | `true` | Loads recent `MemoryItem` rows into context (merged as `long_term_items`). If `false`, memory events and `ProjectMemoryProfile` still apply, but **not** Memory page items. |
| `MEMORY_COMPACTION_CHAR_CAP` | `32000` | Character budget for the assembled v2 bundle. |
| `MEMORY_RESPECT_CONSENT_IN_CONTEXT` | `true` | Skips `MemoryItem` rows whose `consent_state` is not empty/`allowed` in context and in the `memory_items` tool. |
| `MEMORY_ENFORCE_CONSENT_LEDGER` | `false` | When `true`, rows with `principal_id` set require a **granted** latest [`ConsentLedger`](backend/app/api/dpdp.py) row for that principal (`project_id` + `principal_id`). Counter: `memory_items_ledger_blocked_total`. |
| `MEMORY_BATCH_CREATE_ENABLED` | `true` | Enables `POST /api/memory/{pid}/batch` for confirmed multi-adds. |
| `MEMORY_EVENTS_RETENTION_DAYS` | `30` | Prunes old `MemoryEvent` rows (counter `memory_events_pruned_total`). |

On startup, if compaction is on but v2 retrieval is off, the API logs a **warning** (`processdoc.config`) describing the mismatch.

`/metrics/prometheus` emits `# HELP` lines for documented counters (memory, runs, batch), including `user_preference_learning_runs_bumped_total` after successful runs when preferences are updated.

**Related API:** `GET/PATCH /api/projects/{pid}/me/preferences` (user context lines), `GET /api/projects/{pid}/admin/team-personalization` (Owner), `GET/POST/PATCH /api/memory/{pid}` (optional `principal_id` on items).

---

## Frontend Routes

| Route | Description |
|---|---|
| `/projects` | Project list |
| `/projects/{pid}` | Unified Project + Studio workspace (planning + execution + OPAR panels) |
| `/projects/{pid}/runs/{rid}` | Backward-compatible deep link that opens the same unified workspace with run preselected |
| `/projects/{pid}/models` | Analytical models list |
| `/projects/{pid}/models/{mid}` | Model detail + dashboard |
| `/projects/{pid}/models/{mid}/conflicts` | Excel conflict resolution UI |
| `/admin/skills` | Skill registry admin |
| `/tasks` | Scheduled tasks |
| `/memory` | Project memory management |
| `/customize` | Workspace customisation |
| `/permissions` | RBAC and access management |

---

## Visual QA Runtime Requirements

Strict visual QA requires all three:

- `pillow` — image composition helpers
- `pypdfium2` — PDF page rasterization
- `soffice` — LibreOffice headless converter for DOCX/PPTX/XLSX → PDF

If any dependency is missing, visual QA fails closed and downloads remain locked. Check readiness at `GET /api/health/visual-qa`.

---

## Current Status

| Capability | Status |
|---|---|
| Auth (JWT + refresh) | ✅ |
| Project / run CRUD | ✅ |
| Chat-first planning with plan confirmation | ✅ |
| HITL approval gates (plan, mid-run, final review) | ✅ |
| Run state machine + SSE stream | ✅ |
| Multi-agent coordinator (LLM-reasoned, Phase 1) | ✅ |
| Iterative sub-agent tool loop (Phase 2) | ✅ |
| Sub-agent context isolation (Phase 3) | ✅ |
| MCP tool protocol — registry + bridge + tests (Phase 4) | ✅ (enable with `MCP_ENABLED`) |
| Native tool registry (retrieve_context, web_search, etc.) | ✅ |
| Binary artifacts: DOCX, PPTX, XLSX, PDF | ✅ |
| Visual QA gate (image-based, Claude vision) | ✅ |
| Guardrails pipeline (Gates 1–6) | ✅ |
| Skill system v2 cards + companion docs | ✅ |
| LP library integration (local mode) | ✅ |
| Bash tool (sandboxed, guarded) | ✅ |
| Text Editor tool (sandboxed, guarded) | ✅ |
| Analytical modeling (CRUD, scenarios, versions) | ✅ |
| XLSX parsing + schema inference | ✅ |
| Bidirectional sync foundations (dead-letter, checkpoints) | ✅ |
| Conflict resolution UI (per-cell diffs, audit log) | ✅ |
| WebSocket realtime model channel | ✅ |
| Scheduled tasks + scheduler worker | ✅ |
| RBAC (Owner/Editor/Viewer) | ✅ |
| Cowork-inspired Run Studio layout | ✅ |
| Project memory + preferences (assemble_v2, tools, batch API) | ✅ |
| ADD-001 v5 stabilization baseline | ✅ |
| ADD-001 v6 hardening (admission preflight, policy/retry/hook/event strictness) | ✅ |
| Production scale docs, load harnesses, pool/cache env, CI audits | ✅ ([`infra/OPERATIONS.md`](infra/OPERATIONS.md), [`infra/PRODUCTION_TOPOLOGY.md`](infra/PRODUCTION_TOPOLOGY.md), [`infra/load/`](infra/load/)) |
| MCP server live wiring (OneDrive, Slack) | 🔲 Config ready, connector install needed |
| LP library via Graph API (OneDrive) | 🔲 |
| DPDP engine (PII detection, consent ledger) | 🔲 |
| Mobile handoff (push notifications for HITL) | 🔲 |

## ADD-001 v6 Release Checklist

- Apply DB migrations to head (`010` and `011` included).
- Verify run creation can emit `plan_blocked` with `permission_stage` audit events when preflight fails.
- Validate policy rollout mode via `/api/runs/{pid}/permission/simulate` using `enforce_policy=false` before enforce.
- Confirm hook disable durability through `/api/runs/{pid}/hooks/disable` and restart worker/API to verify persisted behavior.
- Ensure event consumers use canonical envelope fields (`schema_version`, `event_type`, `phase`, `ts_ms`, `run_id`, `payload`), especially when `EVENT_CONTRACT_STRICT=true`.
- Run stabilization suite:
  - `pytest -q backend/app/tests/test_auth_hitl.py backend/app/tests/test_add001_architecture.py backend/app/tests/test_qa.py`

---

## Roadmap

- **Graph API LP integration** — connect LP library retrieval to OneDrive/SharePoint via the MCP OneDrive connector (config already scaffolded in `mcp_servers_example.json`)
- **DPDP engine** — upgrade from regex redaction to upload-time PII detection + pseudonymisation; implement append-only Consent Ledger and DPDP rights/consent workflows
- **Tool discovery API** — `GET /api/tools` listing available native + MCP tools with schemas; dynamic registration
- **Tool metrics** — latency histograms per tool, error rates, cost tracking for external services
- **Mobile approval handoff** — push relay to paired mobile device for HITL approvals on scheduled and long-running tasks
- **Multi-tenant MCP isolation** — per-tenant MCP server pools, RBAC for tool access, resource quotas

---

## v4 Hardening Checklist

Full acceptance gates and delivery sequencing:
- `infra/V4_HARDENING_EXECUTION_CHECKLIST.md`
- `v4_rebaseline_reconciliation_2026-03-26.md`

### 1) XLSX Parse/Metrics + Rich Schema Inference
- Real workbook parser (sheet/cell/formula/type/style), not CSV flattening
- Stable cell coordinates with source lineage; schema inference with confidence scores and ambiguity flags
- Parse quality metrics per workbook; `422` rejection gate with structured diagnostics; inference snapshots for drift comparison

### 2) Bidirectional OneDrive/SharePoint Sync Loop
- Pull + push loop against Microsoft Graph-backed Excel files
- Stable `cell_ref_map` with revision IDs; crash-safe sync checkpoints (delta token, etag, last_applied_change_id)
- Dead-letter queue with exponential backoff; sync health exposed via API and UI

### 3) Live Conflict-Resolution UI with Per-Cell Diffs
- Cell-granularity conflict detection with base + local + remote values
- Side-by-side diff UI with sheet/severity filtering; bulk resolve by policy + manual override
- Immutable audit log with actor, timestamp, rationale, chosen side; conflict reopen support

### 4) WebSocket Model/Dashboard Live Updates
- Authenticated WebSocket per project/model; typed events for model changes, scenario recomputes, sync transitions, and KPI refresh
- Monotonic event IDs for ordered replay and gap recovery; fallback to SSE/poll with consistent schema
- Dashboard widgets update incrementally; connection state indicator; stale-data warning when stream is degraded

### Cross-cutting Acceptance Gates
- XLSX import correctly preserves formulas/types across representative finance workbooks
- Bidirectional sync converges under concurrent local/remote edits without silent data loss
- Conflict UI resolves per-cell disputes with full auditability
- Dashboard KPI/chart p95 update latency ≤ 2 s
- Observability: event lag, conflict rate, sync retry counts, WebSocket session health
- Access control enforced per project/model channel; audit logs immutable and queryable; no secret tokens in client logs
