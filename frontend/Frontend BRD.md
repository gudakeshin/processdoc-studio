# ProcessDoc Studio — Frontend Design Specification
**Version:** v4.0
**Status:** Design-Ready
**Stack:** Next.js 14 (App Router) · TypeScript · Tailwind CSS · shadcn/ui · Zustand · React Query

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Design System](#2-design-system)
3. [Application Shell & Navigation](#3-application-shell--navigation)
4. [Route Map](#4-route-map)
5. [Page Designs](#5-page-designs)
   - 5.1 [Dashboard / Project List](#51-dashboard--project-list)
   - 5.2 [Project Home](#52-project-home)
   - 5.3 [Run Studio (Core Screen)](#53-run-studio-core-screen)
   - 5.4 [Document Workspace](#54-document-workspace)
   - 5.5 [Project Settings](#55-project-settings)
   - 5.6 [Admin — Skills & Plugins](#56-admin--skills--plugins)
   - 5.7 [Admin — LP Library Browser](#57-admin--lp-library-browser)
   - 5.8 [DPDP Compliance Centre](#58-dpdp-compliance-centre)
6. [Component Library](#6-component-library)
7. [Real-Time & Streaming UI Patterns](#7-real-time--streaming-ui-patterns)
8. [State Management Architecture](#8-state-management-architecture)
9. [Personalization UI Patterns](#9-personalization-ui-patterns)
10. [Analytical Modeling & Excel UI](#10-analytical-modeling--excel-ui)
11. [Accessibility & Responsiveness](#11-accessibility--responsiveness)
12. [Error States & Empty States](#12-error-states--empty-states)
13. [Animation & Motion](#13-animation--motion)

---

## 1. Design Principles

### 1.1 Core Philosophy

ProcessDoc Studio is a **power tool for consulting practitioners**, not a general-purpose SaaS product. The UI must communicate confidence, precision, and professional quality. Every interaction should reduce cognitive overhead — practitioners are typically in high-pressure, time-sensitive engagements.

| Principle | Description |
|---|---|
| **Progressive Disclosure** | Show only what is needed at each stage. Advanced settings appear contextually, not all at once. |
| **Agentic Transparency** | Make AI activity visible. Users must always see what the agent is doing, why, and with what sources. |
| **Control at Every Step** | HITL (Human-in-the-Loop) is a first-class interaction pattern. Users approve before the system acts. |
| **Calm Density** | Pack useful information into panels without visual noise. Use whitespace and hierarchy, not whitespace instead of density. |
| **Graceful Streaming** | Outputs appear progressively. Partial states must be clearly distinguished from complete states. |

### 1.2 Interaction Model

The core user workflow is a **five-beat rhythm** that every screen should reinforce:

```
Upload → Instruct → Approve → Monitor → Review
```

1. **Upload** — bring in source documents
2. **Instruct** — describe what you want in natural language
3. **Approve** — review and confirm the agent's proposed work plan
4. **Monitor** — watch the run unfold in real time
5. **Review** — inspect outputs, QA scores, sources, and download

---

## 2. Design System

### 2.1 Color Palette

#### Primary Brand Colors
| Token | Hex | Usage |
|---|---|---|
| `primary-900` | `#0F172A` | Page background (dark areas), deep headers |
| `primary-800` | `#1E293B` | Panel backgrounds, sidebar |
| `primary-700` | `#334155` | Card backgrounds, bordered containers |
| `primary-600` | `#475569` | Dividers, subtle borders |
| `primary-400` | `#94A3B8` | Secondary text, placeholder text |
| `primary-100` | `#F1F5F9` | Light mode page background |
| `primary-50` | `#F8FAFC` | Light mode card background |

#### Accent / Action Colors
| Token | Hex | Usage |
|---|---|---|
| `accent-blue` | `#1D4ED8` | Primary CTA buttons, links, active states |
| `accent-blue-light` | `#3B82F6` | Hover states, focus rings |
| `accent-indigo` | `#4F46E5` | Secondary actions, skill tags |
| `accent-violet` | `#7C3AED` | AI/agent activity indicators |

#### Semantic Colors
| Token | Hex | Usage |
|---|---|---|
| `success` | `#16A34A` | Gate pass, QA pass, file uploaded |
| `success-light` | `#DCFCE7` | Success badge backgrounds |
| `warning` | `#D97706` | Gate advisory, QA score 0.6–0.79 |
| `warning-light` | `#FEF3C7` | Warning badge backgrounds |
| `error` | `#DC2626` | Gate block, QA fail, DPDP quarantine |
| `error-light` | `#FEE2E2` | Error badge backgrounds |
| `dpdp-orange` | `#EA580C` | DPDP-specific callouts and banners |
| `dpdp-light` | `#FFF7ED` | DPDP banner backgrounds |

#### AI Activity Color
| Token | Hex | Usage |
|---|---|---|
| `agent-purple` | `#7C3AED` | Streaming indicator, agent step events |
| `agent-purple-light` | `#EDE9FE` | Agent activity backgrounds |

### 2.2 Typography

```
Font Stack:
  Headings:    Inter (700, 600) — system-ui fallback
  Body:        Inter (400, 500) — system-ui fallback
  Mono/Code:   JetBrains Mono — monospace fallback
```

| Scale Token | Size | Weight | Line Height | Usage |
|---|---|---|---|---|
| `text-xs` | 11px | 400 | 1.4 | Badges, timestamps, metadata |
| `text-sm` | 13px | 400/500 | 1.5 | Panel body, list items, captions |
| `text-base` | 15px | 400 | 1.6 | Main body text |
| `text-lg` | 17px | 500/600 | 1.5 | Panel headings, section titles |
| `text-xl` | 20px | 600 | 1.4 | Page titles |
| `text-2xl` | 24px | 700 | 1.3 | Section headings |
| `text-3xl` | 30px | 700 | 1.2 | Hero titles, empty state headings |
| `mono-sm` | 12px | 400 | 1.5 | Agent step text, JSON viewer |
| `mono-base` | 13px | 400 | 1.6 | Code blocks, formula cells |

### 2.3 Spacing & Layout Grid

- Base unit: `4px`
- Panel padding: `16px` (inner), `24px` (outer)
- Card padding: `16px`
- Section gap: `24px`
- Component gap: `8px`
- App uses a **3-panel layout** on the primary Run Studio screen: `280px | flex-1 | 320px`
- Minimum supported viewport: `1280px` width

### 2.4 Elevation / Shadow

| Level | CSS Shadow | Usage |
|---|---|---|
| `shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Flat cards |
| `shadow-md` | `0 4px 6px rgba(0,0,0,0.07)` | Raised panels |
| `shadow-lg` | `0 10px 15px rgba(0,0,0,0.10)` | Modals, dropdowns |
| `shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Overlays, drawers |

### 2.5 Border Radius

| Token | Value | Usage |
|---|---|---|
| `rounded-sm` | `4px` | Badges, chips |
| `rounded` | `6px` | Buttons, inputs |
| `rounded-md` | `8px` | Cards, panels |
| `rounded-lg` | `12px` | Modals, drawers |
| `rounded-xl` | `16px` | Feature cards on marketing-style pages |
| `rounded-full` | `9999px` | Avatars, status dots |

### 2.6 Iconography

- **Icon library:** Lucide React (consistent stroke-width 1.5)
- **Icon sizes:** `16px` (inline), `20px` (button), `24px` (standalone/nav)
- **AI/Agent icon:** custom animated `SparkleIcon` for agent activity states
- Key icons mapped to product concepts:

| Concept | Icon |
|---|---|
| Project | `FolderOpen` |
| Run / Generate | `Zap` |
| Documents | `FileText` |
| Skills | `Puzzle` |
| LP Library | `BookOpen` |
| QA / Quality | `ShieldCheck` |
| Web Search | `Globe` |
| DPDP / Privacy | `Lock` |
| Settings | `Settings2` |
| Agent Activity | `Bot` (animated) |
| Guardrails | `ShieldAlert` |
| Excel | `Table2` |
| Model / Analytics | `BarChart3` |

---

## 3. Application Shell & Navigation

### 3.1 Overall Layout

The application uses a **persistent left sidebar** navigation with a **topbar** for context-specific actions. The content area fills the remaining space.

```
┌─────────────────────────────────────────────────────────────────┐
│  TOPBAR   [Project breadcrumb]          [User] [Notifs] [Help]  │
├──────┬──────────────────────────────────────────────────────────┤
│      │                                                           │
│ SIDE │   CONTENT AREA                                           │
│ BAR  │   (varies by route)                                      │
│      │                                                           │
│ 64px │                                                           │
└──────┴──────────────────────────────────────────────────────────┘
```

### 3.2 Sidebar Navigation

The sidebar is **64px wide** by default (icon-only), expanding to **220px** on hover or when pinned. It contains:

**Top section — Project Navigation**
- `Home` (FolderOpen) — Dashboard / All Projects
- `Run Studio` (Zap) — active project run view *(context-sensitive, appears when inside a project)*
- `Workspace` (Files) — document manager *(context-sensitive)*
- `Settings` (Settings2) — project settings *(context-sensitive)*

**Bottom section — Admin**
- `Skills` (Puzzle) — admin skill browser *(Admin/PracticeLead only)*
- `LP Library` (BookOpen) — OneDrive LP browser *(Admin only)*
- `DPDP Centre` (Lock) — compliance centre *(Owner only, when DPDP enabled)*

**Bottom utility**
- `Help` (HelpCircle)
- User avatar with initials + role badge

### 3.3 Topbar

```
┌─────────────────────────────────────────────────────────────────┐
│  [≡ logo]  Projects / [Project Name] / Runs              [🔔][👤] │
└─────────────────────────────────────────────────────────────────┘
```

- **Breadcrumb** — clickable segments, max 3 levels deep
- **DPDP Banner** — appears below topbar when `dpdp_enabled=true`: orange background strip with "🔒 DPDP Compliance Active — This project processes Indian personal data"
- **Notification bell** — run completions, plan approvals needed, DPDP alerts
- **User menu** — name, role, preferences link, sign out

---

## 4. Route Map

```
/                                   → redirect to /projects
/projects                           → Dashboard (project list)
/projects/new                       → New Project wizard
/projects/[pid]                     → Unified Project + Studio (canonical planning + run execution)
/projects/[pid]/runs/[rid]          → Backward-compatible deep link into Unified Project + Studio (run preselected)
/projects/[pid]/workspace           → Document Workspace
/projects/[pid]/settings            → Project Settings (tabbed)
/projects/[pid]/settings/formats    → Output Types config tab
/projects/[pid]/settings/brand      → Brand Profile tab
/projects/[pid]/settings/dpdp       → DPDP Settings tab
/projects/[pid]/settings/quality    → Quality Settings tab
/projects/[pid]/models              → Analytical Model List
/projects/[pid]/models/[mid]        → Model Editor / Dashboard
/admin/skills                       → Skills & Plugins Browser
/admin/skills/new                   → Skill Creation Wizard
/admin/skills/[sid]/edit            → Skill Editor
/admin/lp-library                   → LP Library Browser
/admin/dpdp                         → DPDP Compliance Centre
```

---

## 5. Page Designs

### 5.1 Dashboard / Project List

**Route:** `/projects`

This is the entry point after login. It shows all projects the user has access to, filtered by their RBAC role.

#### Layout

```
┌────────────────────────────────────────────────────────────┐
│  TOPBAR                                                    │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  My Projects                         [+ New Project]      │
│                                                            │
│  [Search projects...]   [Domain ▾]  [Status ▾]  [Role ▾] │
│                                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ Project Card│  │ Project Card│  │ Project Card│       │
│  └─────────────┘  └─────────────┘  └─────────────┘       │
│                                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ Project Card│  │ Project Card│  │  + New       │       │
│  └─────────────┘  └─────────────┘  └─────────────┘       │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

#### Project Card Component

Each card is `280px × 180px` with:
- **Project name** (text-lg, semibold)
- **Domain tag** — colored chip: Strategy & Ops (blue), Tech & Digital (violet), Enterprise Tech (indigo)
- **DPDP badge** — orange "🔒 DPDP" if enabled
- **Member count** — `3 members` with avatar stack (max 3 shown)
- **Last run timestamp** — `Last run: 2 hours ago`
- **Run count** — `12 runs`
- **Your role** — subtle badge: Owner / Editor / Viewer
- **Quick actions** (visible on hover): Open · New Run · Settings

#### New Project Flow

A **3-step wizard** in a modal or dedicated page:
1. **Name & Domain** — project name, consulting domain selector, optional description
2. **Members** — invite by email, assign roles (Owner/Editor/Viewer)
3. **Settings** — DPDP enable toggle, default style profile, brand profile upload (optional)

---

### 5.2 Project Home

**Route:** `/projects/[pid]`

A summary view showing project status, recent runs, and quick-launch for a new run.

#### Layout

```
┌──────┬─────────────────────────────────────────────────────┐
│      │  [Project Name]   [Domain]  [DPDP]    [Settings]   │
│      ├─────────────────────────────────────────────────────┤
│ SIDE │                                                     │
│ BAR  │  ┌────────────────────┐  ┌──────────────────────┐  │
│      │  │  Quick New Run     │  │  Project Stats       │  │
│      │  │  [input field]     │  │  12 runs  4 docs     │  │
│      │  │  [▶ Generate]      │  │  Avg QA: 0.87        │  │
│      │  └────────────────────┘  └──────────────────────┘  │
│      │                                                     │
│      │  Recent Runs                         [View All →]  │
│      │  ┌──────────────────────────────────────────────┐  │
│      │  │ Run Table (last 5 runs)                      │  │
│      │  └──────────────────────────────────────────────┘  │
│      │                                                     │
│      │  Team Members                       [Manage →]     │
│      │  ┌──────────────────────────────────────────────┐  │
│      │  │ Avatar list with names and roles             │  │
│      │  └──────────────────────────────────────────────┘  │
└──────┴─────────────────────────────────────────────────────┘
```

#### Recent Runs Table

Columns: `Run ID` · `Instruction (truncated)` · `Outputs` · `QA Score` · `Status` · `Started By` · `Timestamp` · `Actions`

Status badges:
- `● Running` — animated purple dot
- `✓ Completed` — green
- `⚠ Warnings` — amber
- `✕ Quarantined` — red (DPDP gate failure)
- `⏸ Plan Pending` — blue (awaiting HITL approval)

---

### 5.3 Run Studio (Core Screen)

**Route:** Canonical `/projects/[pid]` (optional `?run=<rid>`), with `/projects/[pid]/runs/[rid]` as a compatibility route.

This is the heart of the product. It uses a **3-panel layout** that persists through planning and active run execution in one workspace.

#### Overall Layout

```
┌──────┬─────────────────────────────────────┬──────────────────┐
│      │  CENTRE PANEL                       │  RIGHT PANEL     │
│ SIDE │  Run Studio                         │  Context         │
│ BAR  │                                     │  Inspector       │
│      │                                     │                  │
│      │  [LEFT DRAWER — doc manager]        │                  │
└──────┴─────────────────────────────────────┴──────────────────┘
```

The Left Panel (Document Manager) is a **collapsible drawer** triggered from the sidebar or a dedicated toggle, not always visible. The 3-panel layout is:

```
[Left Drawer 280px] | [Centre flex-1] | [Right Panel 320px]
```

---

#### 5.3.1 Left Panel — Document Manager

A collapsible drawer containing the project workspace file tree.

**Header:**
```
Documents  [+Upload]  [⊞ Grid / ≡ List]
```

**File tree:**
```
workspace/[project]/
  ├── 📄 CONTEXT.md              [Edit]
  ├── 📁 source_docs/
  │     ├── 📎 interview_notes.pdf   [🏷 Tags] [🔒 PII]
  │     ├── 📎 org_chart.xlsx        [🏷 Tags]
  │     └── [+ Upload more]
  └── 📁 prior_runs/
        ├── 📁 run_20260120_143000/
        └── 📁 run_20260118_091500/
```

**Document item anatomy:**
- File icon (type-specific color)
- File name (truncated to 180px)
- File size + upload time (text-xs, muted)
- **DPDP badge** — orange `🔒 PII` if PII detected on upload
- **Classification tags** — colored chips (max 3 shown, `+N` overflow)
- **Hover actions:** Preview · Tags · Remove

**Upload zone:**
- Drag-and-drop target that becomes active when files are dragged over the panel
- "Drop files here or click to upload" with accepted types listed
- Upload progress bar per file
- PII scan indicator appears after upload: "Scanning for PII…" → "2 entities redacted"

**CONTEXT.md editor:**
- Click opens a right-aligned inline editor (CodeMirror or simple textarea)
- Auto-saved on blur, debounce 500ms
- Shows last-saved timestamp

---

#### 5.3.2 Centre Panel — Run Studio

This panel contains four sequential UI zones that appear progressively during a run lifecycle.

##### Zone A — Instruction Input (Pre-Run)

```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  What would you like to create?                           │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Generate a process map and RACI matrix for the      │ │
│  │  procurement-to-pay process based on the uploaded    │ │
│  │  interview notes and current SOP.                    │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  Output Format   [SOP Document ▾]  [+ Add format]        │
│                                                            │
│  ┌─── Writing Style ──────────────────────────────────┐  │
│  │  Formality    [Formal ▾]    Tone  [Authoritative ▾]│  │
│  │  Persona      [Senior Director      ]              │  │
│  │  Verbosity    [Balanced ▾]  Audience [C-suite    ] │  │
│  │  [💡 Based on your last 8 runs — save as default?] │  │
│  └────────────────────────────────────────────────────┘  │
│                                                            │
│                              [▶ Generate]                 │
└────────────────────────────────────────────────────────────┘
```

**Instruction textarea:**
- Autofocus on page load
- 4-row minimum, expanding to 8 rows max
- Character count bottom-right (soft limit advisory at 1000 chars)
- Placeholder text cycles through example instructions with a fade transition

**Output format selector:**
- Primary dropdown showing skill display name
- `+ Add format` button opens a pill-selector overlay with all available formats
- Selected formats shown as removable chips below the primary selector
- Custom skill badge on user-defined skills: small star icon

**Style controls:**
- Collapsible section (collapsed by default for returning users with saved preferences)
- Shows current values as summary when collapsed: "Formal · Authoritative · Senior Director"
- **Behavioral learning nudge:** if current values differ from last 8 runs, show a subtle suggestion card: `💡 You've used these style settings 8 times in a row. Save as your default?` — [Save] [Dismiss]

**Generate button:**
- Large, primary, full-width: `▶ Generate`
- Disabled with tooltip if no documents uploaded and no instruction text
- On click: transitions the panel to Zone B (Plan Review)

---

##### Zone B — Plan Review (HITL Approval)

Appears after the Coordinator emits `plan_ready` SSE event. The instruction input collapses and is replaced by the plan review card.

```
┌────────────────────────────────────────────────────────────┐
│  📋 Work Plan — Ready for Approval                        │
│                                                            │
│  Skill: Process & RACI Generation                         │
│                                                            │
│  Context Summary                                          │
│  ─────────────────                                        │
│  ✓ 3 source documents loaded (2,847 chars used)          │
│  ✓ 4 LP snippets retrieved (BM25 score: 0.84)            │
│  ✓ Web search plan: 2 queries prepared                   │
│  ⚠ DPDP flag: 1 document contains Indian PII            │
│                                                            │
│  Sub-agents to be spawned                                 │
│  ─────────────────────────                                │
│  ○ Process Extraction Agent                               │
│  ○ Draw.io / Process Map Agent                            │
│  ○ RACI Agent                                             │
│                                                            │
│  Estimated token budget: 24,800 / 32,000                 │
│  Estimated time: ~4 minutes                               │
│                                                            │
│  [✏ Edit Plan]              [✕ Cancel]  [▶ Approve & Run] │
└────────────────────────────────────────────────────────────┘
```

**Edit Plan mode:**
- Expand into an editable form where users can: remove sub-agents, adjust LP snippet count, toggle web search on/off per agent, add custom instructions per agent
- Changes reflected immediately in token budget estimate

**Approval button:**
- `▶ Approve & Run` is primary green CTA
- On click: button shows spinner "Starting run…" and panel transitions to Zone C

---

##### Zone C — Live Run Monitor

The primary real-time view during generation. Replaces the plan card.

```
┌────────────────────────────────────────────────────────────┐
│  ● Running   [■ Stop]                    ~3 min remaining  │
│  ────────────────────────────────────────────────────────  │
│  COORDINATOR                                               │
│  ✓ Analyse request             0.3s                       │
│  ✓ Load context (32K budget)   2.1s                       │
│  ✓ Select skill                0.1s                       │
│  ✓ Plan approved by user                                  │
│                                                            │
│  PROCESS EXTRACTION AGENT     ● Active                    │
│  ✓ Retrieved context (3 docs)                             │
│  ✓ Web search: "P2P process BPMN taxonomy"               │
│  → Parsing ProcessModel from interview_notes.pdf…        │
│                                                            │
│  DRAW.IO AGENT                 ○ Queued                   │
│  RACI AGENT                    ○ Queued                   │
│                                                            │
│  QA AGENT LOOP                 ○ Pending                  │
│  GUARDRAIL PIPELINE            ○ Pending                  │
│                                                            │
│  ────────────────────────────────────────────────────────  │
│  OUTPUT PREVIEW                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │  Streaming output appears here in real time…       │   │
│  │  _                                                 │   │
│  └────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

**Agent step list:**
- Each step is a row: `[status icon] [step label] [duration]`
- Status icons: `○` pending, `●` active (animated pulse), `✓` done, `⚠` warning, `✕` failed
- Active agent label shows a subtle animated gradient background
- Steps appear with a staggered fade-in as SSE events arrive
- Web search calls show the query string: `🌐 "P2P process BPMN taxonomy"`

**Output preview area:**
- Appears when first `output_chunk` SSE event arrives
- Shows streaming text with a blinking cursor `_`
- For draw.io output, shows a loading placeholder with "Generating process map…" and a skeleton wireframe
- For RACI, shows a table skeleton that populates cell by cell

**QA and Guardrail rows:**
- Collapsed until relevant stage begins
- QA row expands to show: iteration count, scores being calculated
- Guardrail row expands to show gate-by-gate pass/fail as they complete

**Stop button:**
- Secondary destructive button top-right
- Confirmation dialog: "Stop this run? Partial outputs will be saved."

---

##### Zone D — Run Complete / Output Review

Appears after `done` SSE event. The run monitor collapses into a summary bar and the output viewer takes over.

```
┌────────────────────────────────────────────────────────────┐
│  ✓ Completed  QA: 0.91  Gates: 7/7 passed   [View Report] │
│  ────────────────────────────────────────────────────────  │
│  [Process Map] [RACI Matrix] [SOP Document]     Tabs →    │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │                                                      │ │
│  │     [Output Viewer — tab content]                   │ │
│  │                                                      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  [↓ Download All]  [↓ Download Selected]  [↗ New Run]    │
└────────────────────────────────────────────────────────────┘
```

**Output tabs:**
- One tab per output type generated
- Tab label shows output name + quality score badge: `Process Map ✓ 0.94`
- Failing outputs show amber badge: `SOP ⚠ 0.72`

**Output viewer content per type:**
- **Process Map (draw.io):** Embedded draw.io viewer with pan/zoom controls, export to PNG/SVG/XML
- **RACI Matrix:** Interactive HTML table with column filter, CSV export button
- **SOP Document:** Formatted prose viewer with section navigation, DOCX download
- **Narrative/Report:** Formatted prose with source citation tooltips on hover
- **Excel / Model output:** Preview table + XLSX download

---

#### 5.3.3 Right Panel — Context Inspector

Always visible during and after a run. Updates as the run progresses.

```
┌────────────────────────────────────────────────────────────┐
│  Context Inspector                              [▲ Expand] │
│                                                            │
│  ┌── Sources Used ──────────────────────────────────────┐ │
│  │  📎 interview_notes.pdf          relevance: 0.92     │ │
│  │  📎 current_sop.docx             relevance: 0.84     │ │
│  │  📚 P2P Framework LP             relevance: 0.88     │ │
│  │  📚 RACI Best Practices LP       relevance: 0.76     │ │
│  │  🌐 Web: BPMN P2P taxonomy       cached 2m ago       │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌── QA Report ─────────────────────────────────────────┐ │
│  │  Overall: 0.91 ✓ PASSED                              │ │
│  │  Process Map:    0.94 ✓                              │ │
│  │  RACI Matrix:    0.91 ✓                              │ │
│  │  SOP Document:   0.88 ✓                              │ │
│  │  Iterations: 1   Claims verified: 14 / 14            │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌── Guardrails ─────────────────────────────────────────┐ │
│  │  Gate 1 — Schema      ✓ Passed                       │ │
│  │  Gate 2 — Hallucination ✓ Passed                     │ │
│  │  Gate 3 — Brand       ✓ Passed                       │ │
│  │  Gate 4 — References  ✓ Passed                       │ │
│  │  Gate 5 — Plagiarism  ⚠ Advisory (not blocked)      │ │
│  │  Gate 6 — Style       ✓ Passed                       │ │
│  │  Gate 7 — DPDP        ✓ Passed                       │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌── LP Context Panel ──────────────────────────────────┐ │
│  │  [Search LP Library...]                              │ │
│  │  4 snippets used  [Edit for next run]                │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

**LP Context Panel — Edit mode (post-plan-approval):**
- Opens a sheet/drawer showing all retrieved LP snippets
- Each snippet shows: title, section heading, relevance score, triggering classification tags
- Users can: remove a snippet (trash icon), search for additional docs, add a bookmark
- "Save as context template" button at bottom

**Guardrail gate rows:**
- Click to expand shows the specific check details and any corrections made
- Failed gate shows the correction instruction sent to the sub-agent and whether it passed on retry

---

### 5.4 Document Workspace

**Route:** `/projects/[pid]/workspace`

Full-screen view of the project document library — more detailed than the left panel drawer.

#### Layout

```
┌──────┬──────────────────────────────────────────────────────┐
│ SIDE │  Documents                      [↑ Upload]  [⊞ ≡]   │
│ BAR  │                                                       │
│      │  [Search...]  [Domain ▾]  [Type ▾]  [PII only ▾]   │
│      │                                                       │
│      │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐    │
│      │  │ DocCard│  │ DocCard│  │ DocCard│  │ DocCard│    │
│      │  └────────┘  └────────┘  └────────┘  └────────┘    │
│      │                                                       │
│      │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐    │
│      │  │ DocCard│  │ DocCard│  │ DocCard│  │+ Upload│    │
│      │  └────────┘  └────────┘  └────────┘  └────────┘    │
└──────┴──────────────────────────────────────────────────────┘
```

#### Document Card

```
┌────────────────────────────┐
│  [file type icon]          │
│  interview_notes.pdf       │
│  2.3 MB · Uploaded 2h ago  │
│                            │
│  [interview] [strategy]    │
│  [vendor_analysis]         │
│                            │
│  🔒 2 PII entities         │
│  Auto-classified: 95%      │
│                            │
│  [Preview] [Tags] [Remove] │
└────────────────────────────┘
```

#### Document Detail Sheet (slide-over on click)

- Full metadata display
- **Classification editor:** all assigned tags with confidence scores; toggle to enable/disable; free-text add custom tags
- **PII report:** list of redacted entities (type only — no actual values), pseudonym mapping table
- **Usage history:** which runs used this document, relevance scores per run
- **Preview pane:** rendered PDF/DOCX/CSV preview (using browser-native or a library like react-pdf)

---

### 5.5 Project Settings

**Route:** `/projects/[pid]/settings`

Tabbed settings page. Four tabs:

#### Tab 1 — General
- Project name, description (editable)
- Domain selector
- Member management table: Name · Email · Role · Status · Actions (change role, remove)
- Invite new member: email input + role selector + [Invite] button

#### Tab 2 — Output Formats
- List of all active output types (from `output_types.json`)
- Each row: format name · skill · file type · [Edit] [Disable]
- [+ Add Custom Format] opens a form: format ID, display name, description, required skill, file type, template file upload

#### Tab 3 — Brand Profile
- Upload `brand_profile.json` (drag-drop or file picker)
- Live preview of current brand settings:
  - Firm name and short name
  - Prohibited terms list (editable chips)
  - Required disclaimers (editable text areas)
  - Colour palette (color swatches, editable hex values)
  - Tone descriptors (editable tag list)
- [Download Current Profile] button

#### Tab 4 — Data Privacy (DPDP)
- Enable/Disable DPDP toggle — prominent, with confirmation modal ("This will activate Gate 7 and PII scanning for all runs")
- DPO email address input
- SDF mode toggle (Significant Data Fiduciary — enables DPIA and Data Audit controls)
- Cross-border transfer negative list: country chips editor
- PII scanner sensitivity: select which entity types to scan (Aadhaar, PAN, Passport, Voter ID, UPI, biometric, health, etc.)

#### Tab 5 — Quality Settings
- QA pass threshold: numeric slider `0.60` to `1.00` (default 0.80)
- Per-output-type threshold overrides: table with override values
- Max QA iterations: radio buttons (1 or 2)

---

### 5.6 Admin — Skills & Plugins

**Route:** `/admin/skills`

#### Layout

```
┌──────┬───────────────────────────────────────────────────────┐
│ SIDE │  Skills & Plugins            [+ New Skill] [↑ Import] │
│ BAR  │                                                        │
│      │  [Search skills...]  [Domain ▾]  [Type ▾]  [Active ▾]│
│      │                                                        │
│      │  BUILT-IN SKILLS (8)                                  │
│      │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│      │  │SkillCard │ │SkillCard │ │SkillCard │ │SkillCard │ │
│      │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│      │                                                        │
│      │  CUSTOM SKILLS (3)             [Pending Approval: 1]  │
│      │  ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│      │  │SkillCard │ │SkillCard │ │⏳ Pending │              │
│      │  └──────────┘ └──────────┘ └──────────┘              │
│      │                                                        │
│      │  PLUGINS                              [Marketplace →] │
│      │  ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│      │  │ Finance  │ │  Data    │ │Productivity│             │
│      │  └──────────┘ └──────────┘ └──────────┘              │
└──────┴───────────────────────────────────────────────────────┘
```

#### Skill Card Component

```
┌────────────────────────────────┐
│  [icon]  Process & RACI        │
│          Strategy & Ops        │
│                                │
│  Outputs: Process Map,         │
│           RACI Matrix          │
│                                │
│  ✓ Active   v1.2.0             │
│  Used 47 times · Avg QA: 0.89  │
│                                │
│  [View] [Edit] [Versions]      │
└────────────────────────────────┘
```

Custom skills additionally show:
- Creator email
- Sharing scope badge: `project` / `workspace` / `org`
- Pending approval indicator if awaiting PracticeLead sign-off

#### Skill Creation Wizard

5-step stepper at the top, content area below:

```
Step 1 ──● Step 2 ─── Step 3 ─── Step 4 ─── Step 5
         Basic Info
```

**Step 1 — Basic Info:** Name, domain, description, icon upload (optional PNG)
**Step 2 — Output Types:** Checkbox multi-select from `output_types.json`
**Step 3 — Tool Requirements:** Checkbox list of all registered tools; each tool shows description
**Step 4 — Prompt Template:** Monaco editor with variable placeholder syntax, sample instruction input
**Step 5 — Validation & Preview:** Runs JSON schema validation, shows parsed skill card JSON, sharing scope selector, [Create Skill] CTA

#### Plugin governance panel (per plugin)

- Plugin name, description, version
- Installed tools list with toggle per tool (block/allow)
- Execution stats: runs, failures, avg execution time
- Governance rules: require approval toggle per tool, data classification enforcement

---

### 5.7 Admin — LP Library Browser

**Route:** `/admin/lp-library`

#### Layout

```
┌──────┬─────────────────────────────────────────────────────────┐
│ SIDE │  LP Library — OneDrive              [↻ Refresh Index]   │
│ BAR  │  Last indexed: 2 hours ago                              │
│      │                                                          │
│      │  [Search LP documents...]            [+ Bookmark]       │
│      │                                                          │
│      │  ┌─── Folder Tree ──────┐  ┌── Document List ────────┐ │
│      │  │                      │  │                          │ │
│      │  │ 📁 LP-Library/       │  │  [Document rows]        │ │
│      │  │   📁 Strategy-Ops/   │  │                          │ │
│      │  │   📁 Tech-Digital/   │  │                          │ │
│      │  │   📁 Enterprise-Tech/│  │                          │ │
│      │  │   📁 Brand-Assets/   │  │                          │ │
│      │  │   📁 Custom/         │  │                          │ │
│      │  │                      │  │                          │ │
│      │  └──────────────────────┘  └──────────────────────────┘ │
└──────┴─────────────────────────────────────────────────────────┘
```

#### Document List Row

Each row: `[doc icon]` · `Document title` · `Section` · `Modified date` · `Author` · `Classifications` · `[Preview] [Bookmark] [Associate output type]`

**Preview side panel:**
- Rendered document snippet (first ~2000 chars)
- Full metadata
- Classification tags with confidence scores
- "Add to current project's default LP context" toggle

**Bookmarks:**
- Users can bookmark LP documents; bookmarks stored per user per project
- Bookmarked documents are always included in Tier 1 retrieval budget

---

### 5.8 DPDP Compliance Centre

**Route:** `/admin/dpdp`

Available only to project Owners when DPDP is enabled.

#### Layout — 4 tabbed views

**Tab 1 — Consent Ledger**

```
Data Principals                        [+ Register New Principal]
────────────────────────────────────────────────────────────────

[Search principals...]   [Status ▾]   [Purpose ▾]

┌─────────────────────────────────────────────────────────────┐
│ ID (pseudonym) │ Status    │ Purpose     │ Granted   │ Acts  │
│ PERSON_0x2f3a  │ ✓ Granted │ Engagement  │ Jan 12    │ [↗]  │
│ PERSON_0x8b1c  │ ○ Pending │ Analysis    │ —         │ [↗]  │
│ PERSON_0x4e7d  │ ✕ Revoked │ Engagement  │ Dec 3     │ [↗]  │
└─────────────────────────────────────────────────────────────┘
```

**Tab 2 — Rights Requests**

Work queue of pending access, correction, and erasure requests.
Each row: `Principal ID` · `Request type` · `Submitted date` · `Status` · `SLA countdown` · `[Act]`

**Tab 3 — Breach Log**

```
No active incidents

Recent Incidents (30 days)
────────────────────────────────────────────────────────────────
│ Run ID      │ Gate  │ Triggered    │ Timer       │ Status    │
│ run_20260120│ Gate 7│ Jan 20 14:32 │ ✓ Notified  │ Closed    │
└─────────────────────────────────────────────────────────────┘
```

Active quarantine shows a prominent red banner with countdown:
```
🔴 DPDP QUARANTINE — Run run_20260320_142233
   72-hour notification window: 67:23:14 remaining
   [Download Breach Report Template]   [Mark as Notified]
```

**Tab 4 — DPDP Reports**

Per-run report browser: list of runs with their `dpdp_report.json` data summarized:
- PII entities found / redacted
- Consent records used
- Cross-border flags
- Gate 7 result
- [Download full report CSV]

---

## 6. Component Library

### 6.1 Core UI Components

All components built on **shadcn/ui** primitives, styled with Tailwind, extended with product-specific behavior.

#### Button Variants

| Variant | Usage | Style |
|---|---|---|
| `primary` | Main CTA (Generate, Approve) | `bg-accent-blue text-white hover:bg-accent-blue-light` |
| `secondary` | Secondary actions | `border border-primary-600 text-primary-100` |
| `destructive` | Stop, Delete, Revoke | `bg-error text-white` |
| `ghost` | Inline actions, icon buttons | `hover:bg-primary-700` |
| `outline` | Plan Edit, Download | `border border-accent-blue text-accent-blue` |

All buttons: `h-9` (36px), `px-4`, `rounded`, `font-medium text-sm`, transition 150ms

#### Badge Variants

| Variant | Colors | Usage |
|---|---|---|
| `success` | green bg, green text | Gate pass, QA pass, Completed |
| `warning` | amber bg, amber text | Gate advisory, low QA score |
| `error` | red bg, red text | Gate fail, quarantine, error |
| `dpdp` | orange bg, orange text | DPDP-sensitive flag |
| `domain` | blue/violet/indigo | Consulting domain |
| `role` | slate bg | User role |
| `custom` | indigo outline | Custom skill / custom format |
| `pending` | yellow bg | Awaiting approval |

#### Input Variants

- `text` — standard with focus ring `ring-2 ring-accent-blue`
- `textarea` — auto-expanding, same ring
- `search` — prepended SearchIcon, rounded-full
- `file-drop` — dashed border zone with icon

#### Score Gauge

A compact circular or bar gauge component for QA scores:
```
Props: score (0.0–1.0), size (sm|md|lg), showLabel
Colors: 0.00–0.59 → error; 0.60–0.79 → warning; 0.80–1.00 → success
```

#### StatusDot

Animated `8px` dot used for live run status:
- `running` — pulsing violet
- `completed` — solid green
- `warning` — solid amber
- `error` — solid red
- `pending` — solid blue

#### AgentStepRow

```
Props: step (string), status (pending|active|done|warning|error), duration (ms|null), detail (string|null)
```

Renders as a single row in the live run monitor:
```
● Parsing ProcessModel from interview_notes.pdf…    [1.2s]
```

#### GateRow

Renders a guardrail gate status row:
```
Gate 3 — Brand Compliance   [✓ Passed]   [↓ Details]
```
Expandable to show gate detail text.

#### ClassificationTagEditor

Multi-select chip editor with confidence scores:
- Each chip: `[tag label] [score %] [✕]`
- `+ Add tag` inline input
- Chips sorted by confidence score descending

#### StyleProfileForm

Reusable form component for style_profile editing, usable in Run Studio and Project Settings:
```
Props: value (StyleProfile), onChange, compact (boolean)
```
Renders as either inline row (compact) or vertical card form.

---

## 7. Real-Time & Streaming UI Patterns

### 7.1 SSE Connection

The client connects to `GET /api/runs/{rid}/stream` using `EventSource` (or `fetch` with `ReadableStream` for auth headers). Connection managed by a custom React hook:

```typescript
// hooks/useRunStream.ts
function useRunStream(runId: string) {
  // Returns: { events, status, agentSteps, outputChunks, qaReport, guardrailReport }
  // Manages: connection, reconnect on drop (exponential backoff), AbortController (120s timeout)
}
```

### 7.2 SSE Event Handling

| Event Type | UI Effect |
|---|---|
| `plan_ready` | Collapse instruction input; show Plan Review card (Zone B) |
| `step` | Append AgentStepRow to live run monitor; update active agent indicator |
| `output_chunk` | Append text to output preview streaming buffer |
| `qa_report` | Populate QA scores in Context Inspector; show QA row in run monitor |
| `guardrail_event` | Update GateRow component; flash pass/fail color |
| `done` | Transition to Zone D; update run status in project run list via React Query cache invalidation |

### 7.3 Streaming Text Rendering

Output chunks arrive as partial strings. Rendering strategy:
- Buffer chunks in a `useRef` string accumulator
- Flush to DOM via `requestAnimationFrame` throttle (60fps max)
- Render as formatted markdown using `react-markdown` with syntax highlighting
- Blinking cursor `▍` appended to last line while streaming, removed on `done`
- For structured outputs (draw.io XML), buffer full output then render in one step

### 7.4 Optimistic UI

- Document uploads show immediately in the file tree with a loading skeleton, replaced by real data on API confirmation
- CONTEXT.md edits are applied immediately with a 500ms debounce to the API
- Plan edits are local-only until "Approve & Run" is clicked
- WebSocket events from collaborators (document upload, run status) trigger React Query cache invalidation for instant UI updates without polling

---

## 8. State Management Architecture

### 8.1 Zustand Stores

```typescript
// Project-scoped store (one per project, persisted in sessionStorage)
interface ProjectStore {
  project: Project
  documents: Document[]
  members: Member[]
  styleProfile: StyleProfile
  activeRunId: string | null
  // Actions
  setStyleProfile(profile: StyleProfile): void
  addDocument(doc: Document): void
  setActiveRun(runId: string): void
}

// Run-scoped store (one per active run, ephemeral)
interface RunStore {
  runId: string
  status: RunStatus
  agentSteps: AgentStep[]
  outputChunks: Record<OutputType, string>  // accumulator per output type
  qaReport: QAReport | null
  guardrailReport: GuardrailReport | null
  planReady: PlanData | null
  // Actions
  appendStep(step: AgentStep): void
  appendOutputChunk(type: OutputType, chunk: string): void
  setQAReport(report: QAReport): void
  setPlanReady(plan: PlanData): void
}

// App-wide store (user preferences, UI state)
interface AppStore {
  user: User
  behavioralLearning: BehavioralLearningState
  notifications: Notification[]
  sidebarPinned: boolean
}
```

### 8.2 React Query — Server State

All API data fetched and cached via React Query:
- `useProjects()` — project list (5-min stale time)
- `useProject(pid)` — project detail (2-min stale time)
- `useDocuments(pid)` — document list (1-min stale time)
- `useRun(rid)` — completed run data (immutable after completion)
- `useSkills()` — skill list (10-min stale time, invalidated by Redis pub/sub webhook)
- `useLPDocuments(query)` — LP search results (5-min stale time)

### 8.3 Persistence Strategy

| Data | Storage | Lifetime |
|---|---|---|
| JWT auth token | HTTP-only cookie | Session |
| Style profile (last used) | `localStorage` | Persistent |
| Sidebar pin state | `localStorage` | Persistent |
| Draft run instruction | `sessionStorage` | Session |
| SSE event log | React state (RunStore) | Run lifetime |
| Behavioral learning counter | API (users/{uid}/preferences.json) | Persistent |

---

## 9. Personalization UI Patterns

### 9.1 Style Profile Resolution Display

When the style controls form is rendered, the current values are annotated with their source:

```
Formality    [Formal ▾]         📌 Project default
Tone         [Authoritative ▾]  👤 Your preference
Persona      [Senior Director]  👤 Your preference
Verbosity    [Balanced ▾]       ← This run only
Audience     [C-suite exec]     👤 Your preference
```

Legend icons:
- `📌` Project default (Level 1 — set by admin)
- `👤` Saved user preference (Level 2 — persistent)
- `✏` This run only (Level 3 — transient, not saved)

### 9.2 Behavioral Learning Nudge

Triggered when the behavioral learning system detects 8/10 run override pattern:

```
┌─────────────────────────────────────────────────────┐
│  💡 Suggestion                                      │
│  You've used Formal + Authoritative in 8 of your   │
│  last 10 runs on this project.                      │
│  Save as your project default?                      │
│                              [Not Now]  [Save]      │
└─────────────────────────────────────────────────────┘
```

- Appears inline below the style controls form
- "Not Now" dismisses for 5 runs, then re-triggers
- "Save" calls `POST /api/users/preferences` and animates the source annotation to `👤 Your preference`

### 9.3 Admin Visibility Panel

Accessible via Project Settings > Team Personalization (Admin/Owner only):

```
Team Personalization Insights
──────────────────────────────────────────────────────
Override                   Frequency    Top Users
─────────────────────────  ─────────    ──────────────
Formality → Very Formal    78%          Priya, Akash
Audience → Board level     65%          Priya
Verbosity → Concise        52%          All team
──────────────────────────────────────────────────────
[Consider updating project default style profile ↗]
```

### 9.4 Cross-Project Template Export

From user profile or Project Settings:
```
My Preference Templates
──────────────────────────────────────────────────
[Board Materials] [Workshop Mode] [Quick Reports]

[+ Export current project profile as template]
[↑ Import template into this project]
```

---

## 10. Analytical Modeling & Excel UI

### 10.1 Model List

**Route:** `/projects/[pid]/models`

Grid of model cards, each showing:
- Model name and type (user-defined)
- Creation date, creator
- Number of scenarios, number of versions
- Last version timestamp
- Status: `Active` / `Archived`

### 10.2 Model Editor

**Route:** `/projects/[pid]/models/[mid]`

A 3-panel workspace:

```
┌──────────────────────────────────────────────────────────────┐
│  [Model Name]   v_20260320_142233  [Scenarios ▾]  [Version ▾]│
├────────────────────┬─────────────────────┬───────────────────┤
│  INPUT PANEL       │  CALCULATION VIEW   │  OUTPUT PANEL     │
│                    │                     │                   │
│  Data Sources      │  Formula editor or  │  KPI Cards        │
│  [+ Add source]    │  agent-generated    │  Charts           │
│                    │  computation view   │  Tables           │
│  Assumptions       │                     │  [Export XLSX]    │
│  ┌──────────────┐  │                     │  [Export HTML]    │
│  │ Param  Value │  │                     │                   │
│  │ Growth  5%   │  │                     │                   │
│  └──────────────┘  │                     │                   │
│  [+ Add param]     │                     │                   │
│                    │                     │                   │
└────────────────────┴─────────────────────┴───────────────────┘
```

**Assumption cells** (Input Panel):
- Editable inline; click to edit value
- Range validation (min/max defined at creation)
- Shows which outputs depend on each assumption (hover tooltip: "Used in: Revenue Projection, Headcount Plan")
- Locked formula cells shown with a padlock icon — not editable

**Scenario comparison:**
- Dropdown or tab switcher for named scenarios
- Side-by-side mode: splits the output panel vertically to show two scenarios simultaneously
- Variance row at bottom of tables: delta with color coding (positive = green, negative = red)

**Version history:**
- Accessible from the version dropdown at the top
- Timeline shows: version ID, timestamp, who ran it, which scenario
- "Restore this version" button on each historical entry

### 10.3 Excel Integration Panel

Visible within the Model Editor and as a standalone component in the Document Workspace:

```
┌────────────────────────────────────────────────────────────┐
│  Excel Files                             [↑ Upload] [Link] │
│                                                            │
│  ● financial_model.xlsx                 [Synced 1m ago]   │
│    OneDrive · Last modified: you, 2m ago                   │
│    [View Schema] [Open in Excel] [Download] [Unlink]       │
│                                                            │
│  Schema Preview:                                           │
│  Sheet: Assumptions (12 editable cells)                    │
│  Sheet: Revenue Model (computed, locked)                   │
│  Sheet: Dashboard (charts)                                 │
│                                                            │
│  Sync: Every 5 min  [Configure]   Conflicts: 0            │
└────────────────────────────────────────────────────────────┘
```

**Sync conflict indicator:**
- If a conflict is detected: amber badge `1 conflict`
- Click shows: field name, ProcessDoc value, Excel value, timestamp of each, [Keep ProcessDoc] [Keep Excel] buttons

---

## 11. Accessibility & Responsiveness

### 11.1 Accessibility Requirements

| Requirement | Implementation |
|---|---|
| WCAG 2.1 AA | Target for all interactive components |
| Keyboard navigation | Full tab order, logical focus management, skip links |
| Screen reader support | ARIA labels on all icons, live regions for streaming updates |
| Color contrast | Minimum 4.5:1 for body text, 3:1 for large text |
| Focus visible | Custom focus ring: `ring-2 ring-accent-blue ring-offset-2` |
| Error messages | Inline, associated with inputs via `aria-describedby` |
| Agent activity | `aria-live="polite"` on the run step list for screen reader announcements |
| DPDP alerts | `aria-live="assertive"` on breach/quarantine banners |

### 11.2 Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `⌘ + Enter` | Submit / Generate |
| `⌘ + K` | Open command palette (quick navigate, quick run) |
| `⌘ + U` | Upload document |
| `⌘ + /` | Toggle sidebar |
| `Esc` | Close modal / cancel current action |
| `⌘ + D` | Download current output |

### 11.3 Responsive Behavior

The application targets **desktop-first** (1280px+) and degrades gracefully:

| Breakpoint | Behavior |
|---|---|
| `≥ 1280px` | Full 3-panel layout |
| `1024px – 1279px` | Right panel collapses to a tab-trigger; click opens it as overlay |
| `768px – 1023px` | Left drawer hidden by default; center panel full-width |
| `< 768px` | Single-panel view; navigation via bottom tab bar; note: full run functionality limited |

---

## 12. Error States & Empty States

### 12.1 Empty States

Each major page has a purpose-driven empty state:

**No projects yet:**
```
[Illustration: empty folder]
Welcome to ProcessDoc Studio
Create your first project to start generating consulting deliverables.
[+ New Project]
```

**No documents uploaded:**
```
[Upload icon]
No source documents yet
Upload PDFs, DOCX files, transcripts, or spreadsheets to get started.
[↑ Upload Documents]
```

**No runs yet:**
```
[Zap icon]
Ready to generate
Describe the deliverable you need in the instruction box and click Generate.
```

**LP Library — no results:**
```
[BookOpen icon]
No LP documents matched your search.
Try a broader search term, or [↻ refresh the index].
```

### 12.2 Error States

**API error (inline):**
- Toast notification: `⚠ Failed to upload document — please try again.`
- Error boundary for page-level errors with a "Reload" action

**Run failed:**
- Status changes to red with `✕ Failed` badge
- Error message from agent shown in the run monitor
- "Retry Run" button with same instruction pre-filled

**Gate failure (hard block — Gate 7):**
- Full-screen overlay: `🔴 Run Quarantined — DPDP Gate Failure`
- Detail: which check failed, what triggered it
- Actions: [Download Partial Report] [Contact DPO] [View Breach Log]

**SSE connection lost:**
- Banner: `⚠ Lost connection to live run — reconnecting…`
- Auto-reconnects with exponential backoff (max 3 retries)
- On failure: "Refresh to see latest status" with a refresh link

---

## 13. Animation & Motion

### 13.1 Motion Principles

- **Purposeful:** Motion communicates state change, not decoration
- **Fast:** All micro-interactions ≤ 200ms; page transitions ≤ 300ms
- **Restful:** No looping animations except live status indicators (SSE stream, agent activity)

### 13.2 Key Animations

| Element | Animation | Duration | Easing |
|---|---|---|---|
| Page transitions | Fade + slight slide (4px) | 200ms | `ease-out` |
| Panel expand/collapse | Height transition | 200ms | `ease-in-out` |
| Modal open | Scale from 0.95 to 1.0 + fade | 150ms | `ease-out` |
| Agent step appear | Fade in + translate-y 4px | 150ms | `ease-out` |
| Streaming text | No animation (render direct) | — | — |
| Status dot (running) | Pulse keyframe | 1500ms | `ease-in-out` infinite |
| Gate row reveal | Slide-in from left | 200ms | `ease-out` |
| Score gauge fill | Width/dash animation on mount | 600ms | `ease-out` |
| Behavioral nudge | Slide down from top | 250ms | `spring` |
| Upload progress | Width transition | continuous | linear |

### 13.3 Reduced Motion

All animations wrapped in `@media (prefers-reduced-motion: reduce)` overrides that replace transitions with instant state changes. The pulsing status dot changes to a static filled dot.

---

## Appendix A — Component File Structure

```
src/
├── app/                          # Next.js App Router pages
│   ├── projects/
│   │   ├── page.tsx              # Dashboard
│   │   ├── new/page.tsx          # New Project wizard
│   │   └── [pid]/
│   │       ├── page.tsx          # Project Home
│   │       ├── runs/[rid]/page.tsx   # Run Studio
│   │       ├── workspace/page.tsx    # Document Workspace
│   │       ├── settings/page.tsx     # Project Settings
│   │       └── models/
│   │           ├── page.tsx          # Model List
│   │           └── [mid]/page.tsx    # Model Editor
│   └── admin/
│       ├── skills/page.tsx       # Skills Browser
│       ├── lp-library/page.tsx   # LP Library Browser
│       └── dpdp/page.tsx         # DPDP Compliance Centre
├── components/
│   ├── shell/                    # Sidebar, Topbar, DPDPBanner
│   ├── run-studio/               # RunStudio panels, ZoneA-D
│   ├── document-manager/         # File tree, upload, doc cards
│   ├── context-inspector/        # Sources, QA, Guardrails panels
│   ├── skills/                   # SkillCard, Wizard, PluginPanel
│   ├── lp-library/               # Browser, SearchPanel, Bookmarks
│   ├── dpdp/                     # ConsentLedger, BreachLog, RightsQueue
│   ├── models/                   # ModelCard, ModelEditor, ScenarioPanel
│   ├── excel/                    # ExcelIntegrationPanel, SyncStatus
│   └── ui/                       # Primitives: Button, Badge, ScoreGauge,
│                                 # AgentStepRow, GateRow, StyleProfileForm,
│                                 # ClassificationTagEditor, StatusDot
├── hooks/
│   ├── useRunStream.ts           # SSE connection management
│   ├── useStyleProfile.ts        # Style profile resolution + behavioral learning
│   ├── useDocumentUpload.ts      # Upload with PII scan polling
│   └── useWebSocket.ts           # Collaboration WebSocket
├── stores/
│   ├── projectStore.ts           # Zustand project store
│   ├── runStore.ts               # Zustand run store
│   └── appStore.ts               # Zustand app store
├── lib/
│   ├── api.ts                    # API client (axios/fetch wrappers)
│   ├── queryClient.ts            # React Query client config
│   └── sse.ts                    # SSE utilities
└── styles/
    ├── globals.css               # Tailwind base, custom CSS vars
    └── tokens.css                # Design token CSS custom properties
```

---

## Appendix B — API Contract Summary (Frontend-Relevant)

| Endpoint | Method | Used By |
|---|---|---|
| `/api/runs/{rid}/stream` | GET (SSE) | useRunStream hook |
| `/api/runs` | POST | Generate button |
| `/api/runs/{rid}/plan/approve` | POST | Approve & Run button |
| `/api/documents/{pid}/upload` | POST | Upload component |
| `/api/documents/{pid}/{did}/classify` | PATCH | ClassificationTagEditor |
| `/api/projects/{pid}/admin/team-personalization` | GET | Admin Visibility Panel |
| `/api/users/preferences` | GET / PATCH | StyleProfile resolution |
| `/api/workspace/{pid}/skills` | GET / POST | Skills Browser & Wizard |
| `/api/lp-library` | GET (search) | LP Library Browser |
| `/api/dpdp/{pid}/consent` | GET / POST | DPDP Consent Panel |
| `/api/dpdp/{pid}/rights` | GET / POST | Rights Request Queue |
| `/api/projects/{pid}/models` | GET / POST | Model List |
| `/api/projects/{pid}/models/{mid}/versions` | GET | Version History |