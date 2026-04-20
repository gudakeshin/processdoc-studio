# ProcessDoc Studio — Feature Summary

**Last Updated:** April 4, 2026
**Status:** Production Platform (ADD-001 v6 hardening)

---

## Product Overview

ProcessDoc Studio is an **AI-native workflow platform** that converts business instructions and source documents into structured deliverables (DOCX, PPTX, XLSX, PDF, process maps) using a multi-agent orchestration pipeline with human-in-the-loop approval gates, real-time execution visibility, and complete audit trails.

### Core Value Proposition

| Problem | Solution |
|---------|----------|
| Manual, fragmented document workflows | AI-assisted planning + skill-based generation |
| Inconsistent quality across teams | Configurable quality gates + visual QA |
| Poor visibility into execution | Real-time SSE event streaming + audit timeline |
| Weak governance and traceability | Approval gates, hook controls, consent tracking |

---

## Feature Landscape

### 🎯 **1. Project & Workspace Management**

#### Core Capabilities
- **Multi-project support** — Create isolated workspaces with project-level settings and artifacts
- **Role-based access control** — Owner / Editor / Viewer roles with permission pipeline enforcement
- **Document ingestion** — Upload source files (PDF, DOCX, XLSX, images) to project workspace
- **Workspace isolation** — Per-project directories for source files, parsed assets, runs, and outputs
- **Project preferences** — User-defined context lines and behavioral signals per project

**API Endpoints:**
- `POST /api/projects` — Create new project
- `GET /api/projects` — List user's projects
- `GET /api/projects/{pid}` — Get project details
- `PUT /api/projects/{pid}/settings` — Update QA thresholds, hard gates

**UI Pages:**
- `/projects` — Project list with create flow
- `/projects/[pid]` — Project dashboard

---

### 💬 **2. Instruction Planning & Chat**

#### Chat-First Workflow
Users describe deliverables in **natural language**; the system builds a structured plan with decision prompts.

**Key Features:**
- **Conversation memory** — Persistent chat history per run
- **Decision prompts** — Multi-select or free-text questions to refine scope
- **Plan confirmation** — Hash-validated plan review before execution
- **Output type routing** — Users select from supported formats (docx, pptx, xlsx, pdf, process_map, brand_guidelines, raci)
- **Recommended outputs** — AI-suggested output types based on instruction

**Data Model:**
- `Conversation` — Chat session per run
- `ConversationMessage` — Individual messages with role (user/assistant)
- `MemoryEvent` — Context assembly and consent tracking
- `MemoryItem` — User-defined reference materials

**API Endpoints:**
- `POST /api/projects/{pid}/conversation` — Send chat message
- `POST /api/projects/{pid}/conversation/decision` — Submit decision answers
- `POST /api/projects/{pid}/conversation/confirm` — Confirm plan hash

**UI Components:**
- `ZoneAInstruction.tsx` — Chat interface
- `ZoneBPlanReview.tsx` — Plan display and decisions
- `CoordinatorPlanEventBody.tsx` — Extended thinking excerpt + rationale

---

### 🚀 **3. Execution Engine & Run Orchestration**

#### Multi-Phase Run Lifecycle

```
pending
  ↓
plan_review (plan_ready approval gate)
  ↓
running (agent work + optional mid-run HITL gates)
  ↓
review_ready (final approval gate)
  ↓
done / error
```

#### Advanced Execution Features

**Coordinator Planning (Phase 1)**
- LLM-based execution planning with extended thinking
- Structured output plan with rationale and per-output notes
- Plan-aware permission pipeline (inspects plan structure, not just output types)
- Fallback to canonical ordering if planning fails

**Sub-Agent Tool Loop (Phase 2)**
- Multi-round agent execution with token ceilings
- Custom tool registry with aliases (memory_lookup, web_search, bash, text-editor)
- Tool round tracing for audit trail
- Skill-specific tool filtering

**Context Isolation (Phase 3)**
- Per-output AgentContext with sandbox metadata
- Event-driven output emission (no shared mutation)
- Isolated state per agent + merge on completion

**MCP Tool Protocol (Phase 4)**
- JSON-RPC-style stdio interface for external tools
- Server registry with subprocess lifecycle
- Configurable tool timeouts and broken-pipe handling
- Integration-ready for org-specific tools

#### Queuing & Reliability
- **Local queue** (default) — In-memory threaded queue with daemon worker
- **Redis queue** (optional) — Cross-process queue for horizontal scale
- **Dead-letter storage** — Failed runs can be replayed with state recovery
- **Worker heartbeats** — Detect stalled agents and recover

**Run Control & Hooks**
- **Pause / resume / abort controls** — Durable run state transitions
- **Hook system** — Pre/post execution points with policy-driven outcomes
- **Hook controls** — Emergency disable with actor/reason audit trail
- **Permission pipeline** — Multi-stage admission (plan validation, policy checks, consent)
- **Retry modes** — Fast retry vs. cooldown retry with configurable thresholds

**Data Model:**
- `Run` — Execution record with status, plan payload, approval metadata
- `RunEvent` — Typed event envelope (schema_version, event_type, phase, ts_ms, payload)
- `RunTask` — Granular task tracking (phase, status, dependencies, output)
- `HookExecution` — Hook outcome ledger with idempotency
- `HookControl` — Disabled hooks with reason and actor

**API Endpoints:**
- `POST /api/runs` — Create and enqueue new run
- `GET /api/runs/{run_id}` — Get run details with full event timeline
- `GET /api/runs/{run_id}/sse` — Server-sent events stream (real-time updates)
- `POST /api/runs/{run_id}/approve-plan` — Approve plan for execution
- `POST /api/runs/{run_id}/approve-review` — Approve final outputs
- `POST /api/runs/{run_id}/pause` — Pause execution
- `POST /api/runs/{run_id}/resume` — Resume execution
- `POST /api/runs/{run_id}/abort` — Abort run
- `POST /api/runs/{run_id}/retry` — Retry failed run
- `GET /api/runs/{run_id}/dead-letter` — List dead-letter items
- `POST /api/runs/{run_id}/dead-letter/{item_id}/replay` — Replay dead-letter item
- `GET /api/hooks/registered` — List registered hooks
- `POST /api/hooks/{hook_name}/disable` — Disable hook with reason
- `POST /api/hooks/permission-simulation` — Dry-run permission pipeline

**UI Pages:**
- `/projects/[pid]/run/[rid]` — Run Studio (conversation + execution)
- `/projects/[pid]/runs` — Run history

**UI Components:**
- `RunStudio.tsx` — Main orchestration layout (Cowork pattern)
- `ApprovalBanner.tsx` — Unified sticky approval gate
- `ToolActivityFeed.tsx` — Right panel with Activity / Artifacts / Context tabs
- `ZoneCLiveMonitor.tsx` — Coordinator plan with extended thinking

---

### 📄 **4. Skill-Based Generation**

#### Output Types & Skills

**Supported Output Formats:**
- **DOCX** — Narrative documents with formatting, tables, images
- **PPTX** — Slide decks with Deloitte layouts
- **XLSX** — Excel workbooks with analysis, scenarios, bidirectional sync
- **PDF** — Structured documents with merged content
- **Process Maps** — Diagrammatic workflows (draw.io format)
- **Brand Guidelines** — Visual identity documents
- **RACI** — Responsibility matrices

**Skill Registry**
- **Built-in skills** — narrative, raci, sop, process_map, docx, pptx, xlsx, pdf, brand_guidelines (v2 variants available)
- **Custom skills** — User-defined skills with custom tools and output types
- **Skill metadata** — Domain, display name, output types, tools, prompt instructions, quality thresholds, companion files

**Quality Thresholds**
- Per-skill min/max token budgets
- Per-output quality gates (e.g., grammar check, visual QA)
- Configurable max remediation loops

**API Endpoints:**
- `GET /api/workspace/{pid}/skills` — List available skills (built-in + custom)
- `GET /api/workspace/{pid}/skills/{sid}` — Get skill details
- `POST /api/workspace/{pid}/skills` — Create custom skill
- `PUT /api/workspace/{pid}/skills/{sid}` — Update custom skill
- `DELETE /api/workspace/{pid}/skills/{sid}` — Delete custom skill
- `POST /api/workspace/{pid}/skills/{sid}/validate` — Validate skill configuration

**UI Pages:**
- `/admin/skills` — Skill management and creation
- `/projects/[pid]/customize` — Project-level skill selection

**UI Components:**
- `SkillSelector.tsx` — Pick skills for run
- `SkillEditor.tsx` — Custom skill YAML editor

---

### ✅ **5. Quality Gates & Governance**

#### Approval Workflow

**Three-Gate System:**
1. **Plan Review** — Approve instruction plan before execution
2. **Mid-Run HITL** — Optional approval gates during agent work
3. **Final Review** — Approve outputs before finalization

**Visual QA**
- Claude vision-based image evaluation
- Screenshot capture of rendered outputs
- Pass/fail gates with remediation loops
- Configurable max QA loops per project

**Quality Metrics**
- Validator fail rate per skill
- Remediation loop count tracking
- Grammar / tone / structure checks
- Output artifact integrity validation

**API Endpoints:**
- `POST /api/runs/{run_id}/approve-review` — Final QA approval
- `POST /api/runs/{run_id}/retry` — Retry with optional message
- `GET /api/runs/{run_id}/qa-history` — QA attempt history

**UI Components:**
- `ZoneEOutputReview.tsx` — Output review with approve/retry
- `VisualQAGate.tsx` — Vision-based evaluation UI
- `RemediationLoopCounter.tsx` — Show attempt count and limits

---

### 📦 **6. Artifact Management**

#### Output Delivery

**Artifact Formats:**
- Binary files (DOCX, PPTX, XLSX, PDF) streamed as base64 in API
- Process maps as draw.io XML
- Files packaged with full traceability metadata

**Download & Export**
- Single artifact or bundled exports
- File naming with run ID and timestamp
- Checksum validation for integrity
- Archive format support (ZIP)

**API Endpoints:**
- `GET /api/runs/{run_id}/artifacts` — List run artifacts
- `GET /api/runs/{run_id}/artifacts/{artifact_id}/download` — Download single artifact
- `POST /api/runs/{run_id}/artifacts/export` — Export bundle
- `GET /api/runs/{run_id}/artifacts/batch-download` — Download as ZIP

**Data Model:**
- `RunArtifact` — Artifact metadata (type, size, mime, hash)
- Stored in workspace filesystem with content-addressed backup

---

### 🧠 **7. Memory & Context Management**

#### Consent-Aware Context Assembly

**Memory Events**
- Conversation turn recording
- Reference material citations
- Consent changes and audit trail
- Project-wide memory profile

**Memory Items**
- User-uploaded or AI-generated reference docs
- Vectorized for semantic search
- Tracked with consent status

**API Endpoints:**
- `GET /api/memory/{pid}` — Get project memory profile
- `POST /api/memory/{pid}/items` — Add memory item
- `DELETE /api/memory/{pid}/items/{item_id}` — Remove item
- `GET /api/memory/{pid}/items/search` — Semantic search

**UI Pages:**
- `/memory` — Memory browser and consent management

**Data Model:**
- `MemoryEvent` — Chat turn, context addition, consent change
- `MemoryItem` — Reference material with embedding
- `ProjectMemoryProfile` — Aggregated memory stats

---

### 🔒 **8. Governance & Compliance**

#### Permission Pipeline

**Multi-Stage Admission:**
1. **Schema validation** — Output types and plan structure
2. **Policy evaluation** — Rule-based checks (proposal skill targeting, risk classification)
3. **Consent verification** — Memory items must have active consent
4. **Dry-run simulation** — Test policy without executing

**Audit Trail**
- Full run event timeline with timestamps
- Permission stage results (passed / blocked with reason)
- Hook execution outcomes
- Retry and recovery metadata
- User actions (approvals, decisions)

**Data Privacy**
- Consent ledger per project
- DPDP (Data Protection Declaration Process) support
- User rights requests (access, deletion, portability)
- Retention policies

**API Endpoints:**
- `POST /api/runs/{run_id}/permission-simulation` — Dry-run policy
- `GET /api/runs/{run_id}/audit-trail` — Full event history
- `POST /api/dpdp/rights-request` — Submit user rights request
- `GET /api/dpdp/requests` — List requests
- `POST /api/dpdp/requests/{req_id}/respond` — Admin response

**UI Pages:**
- `/admin/dpdp` — Data protection governance
- `/permissions` — Consent and rights management

**Data Model:**
- `ConsentLedger` — Consent state per memory item
- `DPDPRightsRequest` — Data subject rights (access, deletion, etc.)
- `HookControl` — Disabled hooks with reason

---

### 🔄 **9. Advanced Swarm Orchestration**

#### Multi-Agent Teams

**Team Structure:**
- SwarmTeam per run (logical grouping)
- SwarmTeammate with role (worker, reviewer, coordinator)
- Teammate status tracking (idle, working, blocked)

**Communication**
- SwarmMessage for teammate-to-teammate collaboration
- Correlation IDs for request tracing
- Read status tracking

**Task Coordination**
- RunTask with phase (plan, act, review, reflect, refine)
- Dependencies between tasks (blocking relationships)
- Priority-based scheduling
- Estimated duration and actual timing

**API Endpoints:**
- `POST /api/runs/{run_id}/swarm/team` — Create team
- `POST /api/runs/{run_id}/swarm/teammates` — Add teammate
- `POST /api/runs/{run_id}/swarm/messages` — Send message
- `GET /api/runs/{run_id}/swarm/messages` — Get message history

**UI Components:**
- `SwarmDashboard.tsx` — Team visualization
- `TeammateActivityPanel.tsx` — Per-agent status

**Data Model:**
- `SwarmTeam`, `SwarmTeammate`, `SwarmMessage`
- `RunTask` with phase/status/dependencies

---

### 📊 **10. Analytical Modeling** (XLSX-specific)

#### Spreadsheet Collaboration

**Model Lifecycle:**
- XLSX import with schema inference
- Scenario management (baseline, alternatives)
- Version snapshots for audit
- Bidirectional sync (Excel ↔ platform)

**Features:**
- Real-time workbook parsing (openpyxl)
- Cell-level conflict detection
- Delta tokens for efficient sync
- Idempotent replay for reliability

**API Endpoints:**
- `POST /api/models` — Create model from XLSX
- `GET /api/models` — List models
- `POST /api/models/{model_id}/scenarios` — Create scenario
- `POST /api/models/{model_id}/sync` — Bidirectional sync
- `GET /api/models/{model_id}/versions` — Version history

**UI Pages:**
- `/models` — Model browser
- `/models/[mid]` — Model editor with real-time updates

**Data Model:**
- `Model` — Workbook metadata
- `ModelScenario` — Alternative versions
- `ModelConflict` — Cell-level disputes

---

### 🛠️ **11. Operator Tools**

#### Bash & Text Editor (Sandboxed)

**Guarded HTTP API**
- `POST /api/bash` — Execute shell commands (rate-limited, sandboxed)
- `POST /api/text-editor` — Create/read/write files in workspace

**Security:**
- File access restricted to workspace directory
- Rate limiting per user
- Command whitelist (no destructive ops without approval)
- Execution timeout (default 30s)

**Data Model:**
- Execution log with stdin/stdout/stderr
- Exit code tracking

---

### 📅 **12. Scheduled Tasks**

#### Workflow Automation

**Task Types:**
- Recurring (cron-based, supports custom schedules)
- One-time (fire-at timestamp)
- Ad-hoc (manual trigger)

**Scheduling**
- Cron expressions (local timezone)
- Fire-at ISO 8601 timestamps
- Auto-disable after one-time execution

**Task Runs**
- Execution log per task
- Status tracking (queued, running, done, error)
- Result artifact storage

**API Endpoints:**
- `POST /api/tasks` — Create scheduled task
- `GET /api/tasks` — List tasks
- `PUT /api/tasks/{task_id}` — Update task config
- `POST /api/tasks/{task_id}/trigger` — Manual execution
- `GET /api/tasks/{task_id}/runs` — Run history

**UI Pages:**
- `/tasks` — Task dashboard

**Data Model:**
- `ScheduledTask` — Task metadata with cron/fireAt
- `ScheduledTaskRun` — Execution record with status/output

---

### 🔐 **13. Authentication & Authorization**

#### User Management

**Auth Flows:**
- Email/password registration and login
- JWT-based session tokens (configurable expiry)
- Refresh token rotation with jti tracking
- Token revocation support

**Role-Based Access Control (RBAC)**
- **Owner** — Full project admin, run control, member management
- **Editor** — Create runs, approve plans, finalize outputs
- **Viewer** — Read-only access to runs and artifacts

**API Endpoints:**
- `POST /api/auth/register` — Create account
- `POST /api/auth/login` — Login
- `POST /api/auth/refresh` — Refresh JWT
- `POST /api/auth/logout` — Revoke token

**UI Pages:**
- `/login` — Login form

**Data Model:**
- `User` — Email + hashed password
- `RefreshToken` — Server-tracked JWT rotation with revocation

---

### 🔍 **14. Observability & Operations**

#### Monitoring

**Metrics**
- HTTP request timing + correlation IDs
- Prometheus-compatible `/metrics` endpoint
- In-process gauges (queue depth, worker health)
- Alert thresholds (fanout failures, invalid retries, hook timeouts)

**Health & Readiness**
- `GET /api/health` — Simple health check
- `GET /api/health/ready` — Database + Redis connectivity

**Logging**
- Structured JSON logs with context
- Debug mode for detailed trace logging

**Release Gates (ADD-001 v5)**
- Database migrations with backward compatibility
- Contract tests for run-event schema stability
- Runtime resilience tests under stress
- Policy visibility and hook control
- 48h soak window baseline monitoring

---

## Technical Architecture

### Service Boundaries

| Component | Purpose | Tech |
|-----------|---------|------|
| **FastAPI Backend** | HTTP routes, auth, metrics | Python 3.11+ |
| **Run Execution** | LLM coordination + agent work | AsyncIO + Claude API |
| **Queue Runtime** | Local or Redis-backed task queue | Threading / Redis |
| **Frontend** | Conversation + execution UI | Next.js 14 + React |
| **Database** | Project/run/user data | PostgreSQL |
| **Storage** | Artifact + workspace files | Filesystem |
| **MCP Registry** | External tool integration | JSON-RPC over stdio |

### Run Queue Modes

| Mode | When | Scaling |
|------|------|---------|
| `local` | Development / single-machine | In-memory threaded queue |
| `redis` | Multi-worker clusters | Cross-process with external workers |

---

## Security & Compliance

### Built-In Controls

✅ **JWT authentication** with refresh token rotation
✅ **Role-based access control** (Owner/Editor/Viewer)
✅ **Permission pipeline** with multi-stage validation
✅ **Hook controls** for emergency governance
✅ **Audit trail** with full event timeline
✅ **Consent tracking** for memory items
✅ **DPDP rights requests** (access, deletion, portability)
✅ **Sandbox isolation** for bash/text-editor tools
✅ **Rate limiting** on guarded operations

---

## Configuration & Deployment

### Required Environment Variables

```bash
# API Configuration
PROCESSDOC_ENV=production           # or development/staging
JWT_SECRET=<strong-random-32-char>  # REQUIRED: min 32 chars in prod
API_URL=https://your-domain.com
FRONTEND_URL=https://your-domain.com

# LLM
ANTHROPIC_API_KEY=sk-xxx            # Claude API key
ANTHROPIC_THINKING_BUDGET_TOKENS=10000

# Database
DATABASE_URL=postgresql://user:pass@localhost/processdoc
DATABASE_POOL_MIN=5
DATABASE_POOL_MAX=20

# Queue
RUN_QUEUE_BACKEND=local             # or redis
REDIS_URL=redis://localhost:6379    # if redis backend

# Storage
WORKSPACE_ROOT=/data/processdoc     # or S3 path

# Features (optional)
MCP_ENABLED=false                   # Enable MCP servers
COORDINATOR_LLM_PLANNING_ENABLED=true
SWARM_ORCHESTRATION_ENABLED=false
POLICY_BUNDLE_PATH=/etc/policy.yaml
```

### Deployment Models

- **Local Development** — Single Python/Node process, in-memory queue, SQLite optional
- **Docker Compose** — Backend + Frontend + PostgreSQL + Redis
- **Kubernetes** — Horizontal scaling, external database, managed Redis
- **Serverless (Preview)** — CloudRun / Lambda with managed queue

---

## User Experience Flow

### Happy Path: From Instruction to Deliverables

```
1. User describes task in chat
   ↓
2. System suggests output types
   ↓
3. User confirms or refines plan
   ↓
4. [APPROVAL BANNER: "Plan ready — Approve to execute"]
   ↓
5. Coordinator plans execution (with thinking)
   ↓
6. Agents execute in parallel (activity feed shows progress)
   ↓
7. [OPTIONAL: Mid-run HITL gates if triggered]
   ↓
8. Outputs ready for review (visual QA)
   ↓
9. [APPROVAL BANNER: "Review ready — Approve to finalize"]
   ↓
10. Download or export artifacts
```

### Approval Gates (Unified Sticky Banner)

The `ApprovalBanner` component at the bottom of the conversation handles all three gates:
- **plan_ready** — Approve plan hash before execution
- **hitl_gate** — Approve mid-run checkpoint
- **review_ready** — Approve final outputs

Single component replaces three scattered modals → cleaner UX.

---

## Success Metrics (Target KPIs)

| Metric | Target | Status |
|--------|--------|--------|
| First draft time (vs. baseline) | -40% | In progress |
| Runs reaching review-ready | ≥90% | TBD |
| Artifact failure rate | <5% | TBD |
| Event timeline completeness | ≥95% | In progress |
| Plan approval time | <2 min | TBD |

---

## Roadmap (Planned)

### Short Term (Q2 2026)
- [ ] Native Slack integration for approvals
- [ ] Batch run execution (multi-run portfolio)
- [ ] Template library (pre-built run configs)

### Medium Term (Q3 2026)
- [ ] Fine-tuned models for niche output types
- [ ] Advanced conflict resolution (multi-version merges)
- [ ] Cost analytics dashboard

### Long Term (Q4 2026+)
- [ ] Plug-and-play skill marketplace
- [ ] White-label deployment
- [ ] Multi-tenant SaaS offering

---

## Support & Operations

- **Documentation** — `/docs` (OpenAPI schema)
- **Health dashboard** — `/admin/health`
- **Metrics** — `/metrics` (Prometheus format)
- **Logs** — Structured JSON to stdout / file
- **SLOs** — 99.5% uptime, p99 latency <2s on main flows

---

**Built by Boris Cherny & Team**
Cowork Architecture Pattern © Anthropic 2024–2026
