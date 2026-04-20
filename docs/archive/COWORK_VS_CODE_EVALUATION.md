# Claude Cowork vs Claude Code: Architecture Evaluation

**Generated**: 2026-04-08  
**Project**: ProcessDoc Studio  
**Scope**: Full-stack evaluation of codebase against Claude Cowork operating model

---

## Executive Summary

ProcessDoc Studio is **heavily architected around Claude Cowork patterns** with minimal Claude Code traits. The codebase implements a sophisticated multi-agent orchestration system, durable state management, human-in-the-loop approval gates, and a specialized UI designed for collaborative agent execution. It diverges significantly from a typical Claude Code CLI workflow.

**Verdict**: This is a **Cowork-native application**, not a Code-native one. The differences are substantial and systemic.

---

## Part 1: Claude Cowork Implementation (✓ Present)

### 1.1 Four-Layer Agentic Architecture
**Cowork Pattern**: Structured multi-phase execution with planning, execution, and review stages.

**ProcessDoc Implementation**: ✓ **FULLY IMPLEMENTED**
- **Phase 1: LLM-Reasoned Coordinator** (`/backend/app/services/claude.py`)
  - Uses extended thinking capability for structured planning
  - Generates `coordinator_plan` with per-output execution notes
  - Gated by `anthropic_thinking_budget_tokens` config (8000 tokens default)
  - Deterministic reasoning outputs vs. heuristic fallbacks
  
- **Phase 2: Iterative Sub-agent Tool Loop** (`/backend/app/services/claude_tools.py`)
  - Custom tool registry with Anthropic SDK integration
  - Per-output sub-agents (docx, pptx, xlsx, pdf, narrative, process_map)
  - Tool call rounds tracked as `agent_tool_round` events
  - Max rounds/tokens configurable per run
  
- **Phase 3: Sub-agent Context Isolation** (`/backend/app/agents/coordinator_state_manager.py`)
  - Separate `AgentContext` per deliverable
  - Workers receive closure-based `emit_event` callback (no shared state mutation)
  - Output merging strategy for multi-output runs
  
- **Phase 4: MCP Tool Protocol Support** (`/backend/app/services/mcp/`)
  - JSON-RPC substrate protocol implementation
  - Subprocess lifecycle management for external tools
  - Configurable via `/config/mcp_servers.json`

**Difference from Claude Code**: Claude Code is a REPL-style CLI with imperative command execution. ProcessDoc's four-layer model is **explicitly absent** from Code—Code doesn't have planning phases, approved execution plans, or isolation boundaries between sub-agents.

---

### 1.2 Run/Project-Based Execution Model
**Cowork Pattern**: Durable run lifecycle with pause/resume/abort capabilities and audit trails.

**ProcessDoc Implementation**: ✓ **FULLY IMPLEMENTED**
- **Run Lifecycle State Machine**:
  ```
  pending → running → approval_required → running → review_ready → done
  ```
  - Status persisted in `Run.status` (SQLAlchemy ORM)
  - `pause_requested`, `resume_requested`, `abort_requested` flags durable in DB
  - Supports reconciliation on startup for stalled approved runs

- **Durable Controls** (`/backend/app/db/models.py`):
  - `RunControl` table tracks all pause/resume/abort actions with timestamps
  - `hook_controls` table persists hook disable/enable decisions across restarts
  
- **Run Event History** (`RunEvent` table):
  - Immutable append-only log of all events (coordinator_plan, agent_rounds, hook_executions, approvals)
  - SSE stream recovery: clients reconnect and replay event history from last seen event_id
  - Enables audit trail and run replay capability

**Difference from Claude Code**: Claude Code has no concept of "runs"—each prompt is independent. Code doesn't track execution state, can't be paused/resumed, and doesn't maintain persistent event logs. ProcessDoc's run model is a **core architectural requirement** of Cowork.

---

### 1.3 Human-in-the-Loop (HITL) Approval Gates
**Cowork Pattern**: Configurable permission pipeline with plan approval, mid-run gates, and final review.

**ProcessDoc Implementation**: ✓ **FULLY IMPLEMENTED**
- **Permission Pipeline** (`/backend/app/services/permission_pipeline.py`):
  - Admission-time permissions (pre-flight checks before execution)
  - Plan approval gate: `POST /api/runs/{pid}/{rid}/approve` mandatory before execution
  - Mid-run HITL gates: Pauses execution pending human decision
  - Final review gate: Before guardrails/publication
  
- **Unified Approval Banner** (`/frontend/components/run-studio/ApprovalBanner.tsx`):
  - Sticky bottom banner with action buttons (`Approve`, `Reject`)
  - Reactive state: shows `plan_ready`, `hitl_gate`, `review_ready` states
  - Ties to `POST /api/runs/{rid}/approve` endpoint
  
- **Guardrail Pipeline** (`/backend/app/services/guardrails.py`):
  - Content safety checks (visual QA, compliance, DPDP)
  - Can gate publication based on policy
  - Configurable thresholds per guardrail type

**Difference from Claude Code**: Claude Code is interactive but **not gated**—there's no concept of plan approval before execution, no mid-run pause points requiring approval, and no publish gates. Code assumes direct execution; Cowork assumes controlled, auditable execution with human authorization.

---

### 1.4 Two-Column Conversation + Activity Cockpit UI
**Cowork Pattern**: Side-by-side layout with instruction/chat on left, live activity feed on right.

**ProcessDoc Implementation**: ✓ **FULLY IMPLEMENTED**
- **Left Column** (`/frontend/components/run-studio/ZoneAInstruction.tsx`):
  - Instruction chat input
  - Coordinator plan display (reasoning, per-output notes)
  - Execution audit trail (numbered events, timestamps)
  - Output review interface
  
- **Right Panel** (`/frontend/components/run-studio/ToolActivityFeed.tsx`):
  - Skill execution groups (collapsed/expanded tree)
  - Tool call rows with status indicators (running, success, error)
  - Nested tool hierarchy with animated spinners
  - Artifacts panel (generated files)
  - Context tabs (system, project, run-specific)
  
- **Approval Banner** (sticky bottom):
  - Unified control for `plan_ready`, `hitl_gate`, `review_ready` transitions
  - Blocks interaction until approved

**Difference from Claude Code**: Claude Code's interface is linear/scrollable. There's no "activity feed" panel showing live tool execution, no plan review step before execution, and no two-column cockpit design. Code is command-driven; Cowork is result-driven (focus on monitoring/reviewing outputs).

---

### 1.5 Durable State & Async Execution
**Cowork Pattern**: Decoupled request/execution with background workers and event streaming.

**ProcessDoc Implementation**: ✓ **FULLY IMPLEMENTED**
- **Async Queue** (`/backend/app/workers/run_execution_worker.py`):
  - Redis-backed queue or local in-process queue
  - `POST /api/runs` returns immediately with `run_id`
  - Background worker asynchronously dequeues and executes
  - Executor lives in separate thread (embedable consumer mode) or separate process
  
- **Event Streaming** (`GET /api/runs/{pid}/{rid}/stream`):
  - Server-Sent Events (SSE) for real-time updates
  - Client auto-reconnects; server replays event history from last seen event_id
  - Token exchange: `fetchSseToken()` converts JWT to ephemeral SSE token
  
- **Database Persistence**:
  - Run state, plan, outputs all saved to SQLAlchemy ORM
  - Alembic migrations for schema versioning (13 migrations)
  - Run recovery on startup: `reconcile_stalled_approved_runs_on_startup()`

**Difference from Claude Code**: Claude Code executes synchronously in-session with blocking REPL. Cowork separates submission from execution, enabling long-running background work, true pause/resume, and client reconnect resilience. ProcessDoc's worker/queue pattern is **incompatible with Code's REPL model**.

---

### 1.6 Swarm Multi-Agent Teams
**Cowork Pattern**: Orchestration of teammate agents with role definitions and inter-agent communication.

**ProcessDoc Implementation**: ✓ **IMPLEMENTED** (emerging pattern)
- **SwarmTeam Model** (`/backend/app/db/models.py`):
  - `SwarmTeam` tracks team_id, status, run_id
  - `SwarmTeammate` defines teammates by role and conversation state
  - `SwarmMessage` persists inter-agent communication
  
- **TeammateExecutor** (`/backend/app/services/teammate_executor.py`):
  - Executes swarm tasks in subprocess isolation
  - Role-based execution strategies (e.g., git worktree isolation for code agents)
  
- **Swarm Endpoints** (`/backend/app/api/swarm.py`):
  - `POST /api/runs/{rid}/swarm/create-team`
  - `POST /api/runs/{rid}/swarm/execute-task`
  - Team communication via message passing

**Difference from Claude Code**: Claude Code has no swarm capability. It's single-agent, imperative. ProcessDoc implements multi-agent teams with role isolation, async task execution, and inter-agent messaging—a **core Cowork feature missing entirely from Code**.

---

## Part 2: Key Differences from Claude Code (✗ Not Present in Code)

### 2.1 Project/Workspace Context
**Cowork Requirement**: Projects group runs, manage members, track shared context.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Project Model** | `Project` ORM with membership, role-based access | N/A (no projects) |
| **Membership** | User×Project→Role (Owner/Editor/Viewer) | N/A |
| **Shared Context** | `ProjectMemoryProfile` stores tiered context | N/A (user context only) |
| **Memory Consent** | `MemoryConsent` table tracks data usage per member | N/A |

**Implication**: Code is single-user; Cowork is multi-user collaborative.

---

### 2.2 Permission & Authorization Pipeline
**Cowork Requirement**: Role-based project access + run-level approval gates.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Authentication** | JWT with refresh token rotation, jti revocation | N/A (no auth model) |
| **Authorization** | `require_project_role(project_id, allowed_roles)` RBAC | N/A |
| **Run Approval** | `POST /api/runs/{rid}/approve` mandatory before execution | N/A |
| **Permission Pipeline** | Admission control + plan gate + HITL + review gate | N/A |
| **Guardrails** | Content safety, DPDP compliance, visual QA checks | N/A |

**Implication**: Code assumes trusted environment. Cowork assumes untrusted, multi-stakeholder environment requiring explicit authorization at multiple gates.

---

### 2.3 Deliverable Output Types
**Cowork Pattern**: Structured output generation with quality validation.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Output Types** | 6 types: Narrative, Process Map, RACI, SOP, Excel, Slide Deck, PDF | N/A (text only) |
| **Sub-agent Per Type** | Docx, Pptx, Xlsx, Pdf sub-agents generate structured outputs | N/A |
| **Quality Loops** | Critique-revise cycles per output type | N/A |
| **Template Inheritance** | Brand/quality settings cascade from project → output | N/A |

**Implication**: Code produces ephemeral text; Cowork produces validated, branded, auditable artifacts.

---

### 2.4 Extended Thinking & Structured Planning
**Cowork Enhancement**: Uses Claude's extended thinking for deterministic planning.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Extended Thinking** | `claude_generate_with_thinking()` for coordinator planning | N/A (standard chat API) |
| **Thinking Budget** | `ANTHROPIC_THINKING_BUDGET_TOKENS` (default 8000) | N/A |
| **Plan Output** | Structured `ExecutionPlan` with per-output notes | N/A |
| **Quality Gates** | Thinking excerpt cached for audit trail | N/A |

**Implication**: ProcessDoc deterministically plans work before execution. Code is opportunistic—no planning phase.

---

### 2.5 Database & Durable State
**Cowork Requirement**: Persistent run history, event log, configuration.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Database** | PostgreSQL/SQLite with SQLAlchemy ORM | N/A (in-memory only) |
| **Migrations** | Alembic versioned schema (13 migrations) | N/A |
| **Event Log** | Immutable `RunEvent` append-only log | N/A |
| **Run Persistence** | `Run` table: status, plan, outputs, flags, errors | N/A |
| **Recovery** | Startup reconciliation for stalled runs | N/A |

**Implication**: Code is ephemeral; Cowork is auditable and recoverable.

---

### 2.6 Memory & Long-Term Context
**Cowork Pattern**: Persistent memory across runs with consent tracking and compaction.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Memory Items** | `MemoryItem` ORM with retention policy (30 days default) | N/A |
| **Consent Ledger** | `MemoryConsent` tracks data usage authorization | N/A |
| **Memory Compaction** | `memory_compaction_v1_enabled` flag for semantic retrieval | N/A |
| **Tiered Context** | `TieredContextEngine` (immediate → project → system) | N/A |

**Implication**: Code is stateless per-session; Cowork accumulates institutional memory.

---

### 2.7 Background Execution & Queueing
**Cowork Pattern**: Async execution decoupled from request.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Queue Backend** | Redis or local queue with dead-letter support | N/A (synchronous) |
| **Admission Control** | Per-global, per-project, per-user limits | N/A |
| **Worker Threads** | Background `RunExecutionWorker` thread | N/A |
| **Health Checks** | `/health/ready` polls DB + Redis + queue status | N/A |
| **Scheduler** | Cron-based scheduled runs from DB | N/A |

**Implication**: Code blocks on execution; Cowork decouples request from work.

---

### 2.8 Tool & Hook Execution Tracking
**Cowork Pattern**: Durable audit trail of all tool invocations.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Hook Execution** | `HookExecution` ORM row per hook invocation | N/A |
| **Hook Controls** | Disable/enable decisions persisted across restarts | N/A |
| **Tool Rounds** | `agent_tool_round` events streamed to client | N/A |
| **Bash Tool** | Allowlist-based execution with Docker option | Tool available but no audit trail |
| **Bash Audit Log** | Optional audit log to disk + database | N/A |

**Implication**: Code offers tools; Cowork audits tool usage.

---

### 2.9 Real-Time Activity Feed
**Cowork UI Pattern**: Live skill execution visualization with status tracking.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Activity Feed** | Tree view of skill execution groups → tool calls | CLI text output only |
| **Nested Status** | Running/success/error indicators per tool | N/A |
| **Animated Spinners** | Visual feedback for in-progress work | N/A |
| **Server Event Stream** | SSE broadcasts executor events to all connected clients | N/A (single client, blocking) |

**Implication**: Code is text-centric; Cowork is visual and real-time.

---

### 2.10 Observability & Tracing
**Cowork Enhancement**: Optional Langfuse + OpenTelemetry integration.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Structured Logging** | JSON mode for machine parsing (`STRUCTURED_LOGGING_ENABLED`) | Ad-hoc text logging |
| **Correlation IDs** | `x-request-id` header propagated through requests | N/A |
| **Langfuse Tracing** | Optional integration for LLM tracing (`LANGFUSE_ENABLED`) | N/A |
| **OpenTelemetry** | Optional OTel SDK for distributed tracing | N/A |
| **Circuit Breaker** | Claude API failure handling with exponential backoff | N/A |

**Implication**: ProcessDoc is observable at scale; Code is ad-hoc logging.

---

### 2.11 MCP (Model Context Protocol) Integration
**Emerging Cowork Feature**: Native support for MCP servers.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **MCP Protocol** | JSON-RPC substrate in `/services/mcp/protocol.py` | MCP client only (no server bridging) |
| **Server Config** | `/config/mcp_servers.json` declarative setup | N/A |
| **Subprocess Lifecycle** | Registry manages server start/stop | N/A |
| **Tool Bridging** | `try_mcp_tool_call()` / `call_mcp_tool()` | N/A |
| **Gated Feature** | `MCP_ENABLED` flag (default off) | Standard feature |

**Implication**: ProcessDoc bridges MCP servers as coordinated tools. Code invokes MCP as client.

---

### 2.12 Configuration as Code
**Cowork Pattern**: Declarative configuration with environment validation.

| Aspect | ProcessDoc | Claude Code |
|--------|-----------|-----------|
| **Settings Model** | Pydantic `BaseSettings` with validation | CLI args only |
| **Env File Loading** | `.env` file with explicit path calculation | `.env` auto-discovered |
| **Production Checks** | `JWT_SECRET` length validation, DATABASE_URL mandatory | N/A |
| **Feature Flags** | 20+ toggles (SCHEDULER, MCP, OTEL, SWARM, etc.) | Single config file |
| **Token Budgets** | Per-run, per-call, thinking budget limits | No budget tracking |

**Implication**: ProcessDoc is a configurable platform; Code is a fixed tool.

---

## Part 3: Summary Table

### Cowork Features Present in ProcessDoc
| Feature | Cowork Expected | ProcessDoc | Status |
|---------|-----------------|-----------|--------|
| Four-layer architecture | ✓ | Extended thinking + multi-phase execution | ✅ |
| Run lifecycle with state machine | ✓ | Durable DB with pause/resume/abort | ✅ |
| Multi-user project context | ✓ | Membership, RBAC, shared memory | ✅ |
| HITL approval gates | ✓ | Plan approval + mid-run gates + review | ✅ |
| Two-column cockpit UI | ✓ | ZoneA + ToolActivityFeed layout | ✅ |
| Event audit trail | ✓ | Immutable RunEvent log | ✅ |
| Async background execution | ✓ | Redis queue + worker threads | ✅ |
| Structured output types | ✓ | 6 output types with sub-agents | ✅ |
| Memory persistence | ✓ | MemoryItem with retention policy | ✅ |
| Swarm multi-agent | ✓ | SwarmTeam, TeammateExecutor | ✅ |
| MCP integration | ✓ | JSON-RPC server bridge | ✅ |
| Observability | ✓ | Langfuse, structured logging, OTel | ✅ |

### Claude Code Features Absent from ProcessDoc
| Feature | Claude Code | ProcessDoc | Status |
|---------|------------|-----------|--------|
| REPL-style sync execution | ✓ | Async queue-based | ✅ Replaced |
| Command-line interface | ✓ | Web UI + REST API | ✅ Replaced |
| Ephemeral text output | ✓ | Durable structured artifacts | ✅ Replaced |
| Interactive imperative prompts | ✓ | Instruction + approval gates | ✅ Replaced |
| File system interaction (read/write/bash) | ✓ | Toolbox + audited execution | ⚠️ Limited |
| Multi-document editing | ✓ | Web-based editing UI | ✅ Replaced |
| Keyboard shortcuts | ✓ | Web UI (no shortcuts) | ❌ Not present |
| IDE integration | ✓ | Standalone web app | ❌ Not present |
| `.claude/` workspace config | ✓ | Backend config only | ⚠️ Partial |

---

## Detailed Differences by Component

### API & Server Model

**Claude Code**: 
- Synchronous REPL prompt → response
- Blocking tool execution in-process
- Single-session state (in-memory)

**ProcessDoc**:
- Asynchronous REST API with queue-based execution
- Background worker processes (decoupled)
- Durable multi-project state (DB)
- Multi-session concurrency support

### State Management

**Claude Code**:
- Session-local (TypeScript context)
- Lost on session termination
- User context only

**ProcessDoc**:
- PostgreSQL (persistent across restarts)
- Event sourcing for audit trail
- Project × User × Run hierarchy
- Memory compaction and retention policies

### Authorization

**Claude Code**:
- None (assumed trusted single user)

**ProcessDoc**:
- Multi-user with RBAC (Owner/Editor/Viewer)
- JWT with refresh token rotation
- Per-run approval gates
- Guardrail gating before publication

### UI Model

**Claude Code**:
- Linear chat interface (REPL-style)
- Markdown text rendering
- Inline artifacts (code, text)

**ProcessDoc**:
- Two-column cockpit (chat + activity feed)
- Real-time tool execution visualization
- Approval banner for gates
- Structured deliverable artifacts (docx, pptx, xlsx, pdf)

### Tool Execution

**Claude Code**:
- Synchronous function calls
- Direct file system access (read/write/bash)
- No audit trail

**ProcessDoc**:
- Asynchronous tool rounds with max iterations
- Custom tool registry with allowlist
- MCP server bridge support
- Audited execution with HookExecution rows
- Circuit breaker on API failures

### Output Management

**Claude Code**:
- Ephemeral chat messages
- No structured output types
- Client-side saving only

**ProcessDoc**:
- Persistent deliverables (Process Map, Narrative, SOP, RACI, Excel, Slides, PDF)
- Per-output quality loops (critique-revise)
- Brand/quality settings per project
- Server-side storage + download capability

### Execution Model

**Claude Code**:
- Imperative: user enters prompt → Code executes → displays result
- No planning phase
- No pause/resume/abort

**ProcessDoc**:
- Declarative: user instruction → coordinator plans → approval required → execution → approval → review
- Extended thinking for deterministic planning
- Full pause/resume/abort lifecycle
- Recovery on restart

---

## Conclusion

**ProcessDoc Studio is a native Cowork application that implements nearly all Cowork patterns and requirements.** It is fundamentally incompatible with Claude Code's REPL-based, synchronous, single-user model.

### Key Takeaways:

1. **Architecture**: ProcessDoc = four-layer orchestration + durable state. Code = synchronous REPL.
2. **State**: ProcessDoc = database-backed, multi-project, multi-session. Code = session-local.
3. **Execution**: ProcessDoc = async queue + background workers. Code = blocking in-process.
4. **Authorization**: ProcessDoc = RBAC + approval gates. Code = no auth.
5. **UI**: ProcessDoc = cockpit (chat + activity). Code = REPL (linear).
6. **Output**: ProcessDoc = structured deliverables (6 types). Code = ephemeral text.
7. **Audit**: ProcessDoc = immutable event log. Code = no trail.
8. **Memory**: ProcessDoc = persistent with retention policy. Code = none.

### Recommendation:

If the goal is to align this codebase with Claude Code patterns, a **complete architectural rewrite** would be required. The two systems are fundamentally different in design philosophy:
- **Code** = imperative, REPL-based, single-session, file-centric
- **Cowork** = declarative, event-driven, multi-session, artifact-centric

**Current state**: This codebase should remain Cowork-aligned and continue to develop along that trajectory. Attempting to retrofit Code patterns would sacrifice all Cowork benefits (durable state, HITL, audit trails, multi-user, scheduled execution, swarm teams).

---

## Files Referenced in This Analysis

### Backend Critical Files
- `/backend/app/main.py` - FastAPI app setup, lifespan
- `/backend/app/agents/coordinator.py` - Multi-phase orchestration
- `/backend/app/services/claude.py` - Extended thinking planner
- `/backend/app/services/claude_tools.py` - Tool loop executor
- `/backend/app/services/permission_pipeline.py` - Approval gates
- `/backend/app/workers/run_execution_worker.py` - Async executor
- `/backend/app/db/models.py` - ORM schema (Run, RunEvent, Project, etc.)
- `/backend/app/core/config.py` - Settings validation

### Frontend Critical Files
- `/frontend/app/layout.tsx` - Root provider setup
- `/frontend/components/run-studio/RunStudio.tsx` - Cockpit orchestrator
- `/frontend/components/run-studio/ApprovalBanner.tsx` - HITL gate UI
- `/frontend/components/run-studio/ToolActivityFeed.tsx` - Activity feed
- `/frontend/hooks/useRunStudio.tsx` - State orchestration (1111 lines)
- `/frontend/lib/auth-context.tsx` - Auth & token management
- `/frontend/lib/api.ts` - API client with retry/timeout

---

**End of Report**
