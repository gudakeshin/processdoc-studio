# Wiki System - File Reference Guide

Complete list of all files created for the wiki system implementation.

## Quick Navigation

- **[Backend Services](#backend-services)** (5 files)
- **[Frontend Components](#frontend-components)** (12 files)
- **[Documentation](#documentation)** (3 files)

---

## Backend Services

### 1. `backend/app/services/wiki_operations.py`
**Purpose:** Tier 1 retry framework with exponential backoff
- **Size:** 450 LOC
- **Key Functions:**
  - `exponential_backoff(attempt: int) -> float`
  - `classify_error(error: Exception) -> bool`
  - `wiki_ingest_with_retry(source_data: dict) -> tuple`
  - `wiki_query_with_retry(question: str) -> tuple`
  - `wiki_lint_with_retry(wiki_path: str) -> tuple`
- **Tests:** `backend/app/tests/test_wiki_operations.py` (24 tests)

### 2. `backend/app/services/wiki_corrections.py`
**Purpose:** Tier 2 auto-correction for data quality
- **Size:** 330 LOC
- **Class:** `DataCorrector`
- **Methods:**
  - `correct_frontmatter(page_dict) -> (dict, list)`
  - `correct_references(page_dict, wiki_index) -> (dict, list)`
  - `correct_formatting(page_text) -> (str, list)`
  - `correct_data_types(page_dict) -> (dict, list)`
  - `correct_duplication(all_pages) -> (list, list)`
  - `correct_stale_references(page_dict, log) -> (dict, list)`
- **Tests:** `backend/app/tests/test_wiki_corrections.py` (33 tests)

### 3. `backend/app/services/wiki_qa.py`
**Purpose:** Tier 3 QA/linting with health checks
- **Size:** 410 LOC
- **Class:** `WikiQAEvaluator`
- **Methods:**
  - `evaluate_wiki_health(wiki_root, log_file) -> dict`
  - `_check_contradictions(all_pages) -> list`
  - `_check_orphans(all_pages, index) -> list`
  - `_check_missing_references(all_pages, index) -> list`
  - `_check_broken_links(all_pages) -> list`
  - `_check_coverage_gaps(all_pages, log) -> list`
  - `_check_divergence(project_wiki, lp_wiki) -> list`
  - `_check_staleness(all_pages, log, days) -> list`
- **Tests:** `backend/app/tests/test_wiki_qa.py` (21 tests)

### 4. `backend/app/services/wiki_integrations.py`
**Purpose:** Integration with ProcessDoc v2 systems
- **Size:** 580 LOC
- **Classes:**
  - `WikiMemoryIntegration` - Memory items → wiki pages
  - `WikiRunIntegration` - Run artifacts → wiki pages
  - `WikiConversationIntegration` - Conversation digests → wiki pages
  - `WikiCoordinatorIntegration` - Context retrieval for planning
  - `WikiLeadingPracticesIntegration` - LP wiki repository
- **Key Methods:**
  - `ingest_memory_item_to_wiki(memory_item) -> dict`
  - `ingest_run_artifact_to_wiki(run_id, project_id) -> dict`
  - `digest_conversation_to_wiki(conversation_id, project_id) -> dict`
  - `query_wiki_for_context(objective, project_id) -> list`
  - `get_leading_practices_from_wiki(topic, category) -> list`
  - `propose_learning_to_lp_wiki(page_id, reason) -> dict`
- **Tests:** `backend/app/tests/test_wiki_integration.py` (30 tests)

### 5. `backend/app/api/wiki.py`
**Purpose:** REST API endpoints for wiki operations
- **Size:** 550 LOC
- **Endpoints:** 13 total
  - `POST /api/wiki/{wiki_type}/ingest`
  - `POST /api/wiki/{wiki_type}/ingest/from-memory`
  - `POST /api/wiki/{wiki_type}/ingest/from-run`
  - `POST /api/wiki/{wiki_type}/ingest/from-conversation`
  - `POST /api/wiki/{wiki_type}/query`
  - `GET /api/wiki/{wiki_type}/context`
  - `POST /api/wiki/{wiki_type}/lint`
  - `GET /api/wiki/{wiki_type}/pages`
  - `GET /api/wiki/{wiki_type}/pages/{page_id}`
  - `GET /api/wiki/{wiki_type}/search`
  - `POST /api/wiki/{wiki_type}/pages/{page_id}/promote`
  - `GET /api/wiki/{wiki_type}/stats`
  - `GET /health`
- **Tests:** `backend/app/tests/test_wiki_api.py` (39 tests)

### 6. `backend/app/db/wiki_models.py`
**Purpose:** Data models for wiki entities
- **Size:** 200 LOC
- **Models:**
  - `WikiPage` - Wiki page data and metadata
  - `WikiLog` - Operation log for audit trail
  - `WikiIndex` - Catalog of all pages
- **Fields Include:**
  - Page content, metadata, links
  - Operation tracking, timestamps
  - Source traceability (memory, runs)

---

## Frontend Components

### Core Wiki Components

#### 1. `frontend/components/wiki/WikiDashboard.tsx`
**Purpose:** Main overview with statistics and health
- **Size:** 250 LOC
- **Props:**
  ```typescript
  wikiType: 'leading_practice' | 'project'
  projectId?: string
  ```
- **Features:**
  - Total pages, pages this week, health status
  - Category breakdown cards
  - Confidence distribution bars
  - Health alerts with severity
  - Quick action buttons
- **API:** `GET /api/wiki/{wiki_type}/stats`

#### 2. `frontend/components/wiki/WikiSearch.tsx`
**Purpose:** Full-text search with faceted filtering
- **Size:** 300 LOC
- **Props:**
  ```typescript
  wikiType: 'leading_practice' | 'project'
  projectId?: string
  ```
- **Features:**
  - Search input with submit
  - Category filter sidebar
  - Confidence filter sidebar
  - Results with snippet preview
  - Facet counts and statistics
- **API:** `GET /api/wiki/{wiki_type}/search?q=...&category=...&confidence=...`

#### 3. `frontend/components/wiki/WikiIngest.tsx`
**Purpose:** Source ingestion with 4 source types
- **Size:** 380 LOC
- **Props:**
  ```typescript
  wikiType: 'leading_practice' | 'project'
  projectId?: string
  ```
- **Source Types:**
  1. URL - Web article ingestion
  2. Document - File upload (PDF/Word/Excel)
  3. Run Artifact - Run ID input
  4. Conversation - Conversation ID input
- **Features:**
  - Radio button source type selector
  - Dynamic form fields
  - Progress tracking
  - Results with corrections and QA
  - Success/error feedback
- **API:** `POST /api/wiki/{wiki_type}/ingest`

#### 4. `frontend/components/wiki/WikiBrowse.tsx`
**Purpose:** Paginated list with filtering and sorting
- **Size:** 400 LOC
- **Props:**
  ```typescript
  wikiType: 'leading_practice' | 'project'
  projectId?: string
  ```
- **Features:**
  - Full page pagination
  - Category filter
  - Confidence filter
  - Sort options (title, date, relevance)
  - Items per page selector
  - Summary statistics
- **API:** `GET /api/wiki/{wiki_type}/pages?limit=...&offset=...&sort=...`

#### 5. `frontend/components/wiki/WikiPage.tsx`
**Purpose:** Single page display with metadata
- **Size:** 350 LOC
- **Props:**
  ```typescript
  wikiType: 'leading_practice' | 'project'
  pageId: string
  projectId?: string
  ```
- **Tabs:**
  1. Content - Full markdown rendering
  2. Links - Inbound/outbound cross-references
  3. Metadata - Frontmatter and sources
- **Features:**
  - Breadcrumb navigation
  - Title and confidence badge
  - Action buttons (Edit, Promote, More)
  - Metadata display
  - Link graphs (inbound/outbound)
- **API:** `GET /api/wiki/{wiki_type}/pages/{page_id}`

#### 6. `frontend/components/wiki/WikiQuery.tsx`
**Purpose:** Question answering interface
- **Size:** 400 LOC
- **Props:**
  ```typescript
  wikiType: 'leading_practice' | 'project'
  projectId?: string
  initialQuestion?: string
  ```
- **Features:**
  - Textarea for question input
  - Optional QA evaluation toggle
  - Answer synthesis display
  - Citations with source links
  - Quality score and suggestions
  - Related questions (expandable)
  - Query history tracking
  - Save/Share/Edit actions
- **API:** `POST /api/wiki/{wiki_type}/query`

#### 7. `frontend/components/wiki/WikiLint.tsx`
**Purpose:** Health check and issue resolution
- **Size:** 450 LOC
- **Props:**
  ```typescript
  wikiType: 'leading_practice' | 'project'
  projectId?: string
  autoRun?: boolean
  ```
- **Features:**
  - One-click health check execution
  - Auto-fix toggle
  - Status cards (passed/issues/severity)
  - Issue breakdown by type
  - 7 issue types with expandable details
  - Severity filtering
  - Suggestions with affected pages
  - Resolve/Ignore/Edit actions
- **API:** `POST /api/wiki/{wiki_type}/lint`

#### 8. `frontend/components/wiki/WikiPagePreview.tsx`
**Purpose:** Inline preview popup
- **Size:** 200 LOC
- **Props:**
  ```typescript
  pageId: string
  wikiType: 'leading_practice' | 'project'
  projectId?: string
  trigger?: 'hover' | 'click' | 'none'
  children?: React.ReactNode
  className?: string
  ```
- **Features:**
  - Hover/click trigger modes
  - Smart positioning (avoids off-screen)
  - Summary with metadata
  - Confidence badge
  - Updated date, reference count
  - Outbound link count
  - View full page link
- **API:** `GET /api/wiki/{wiki_type}/pages/{page_id}/preview`

### Integration Components

#### 9. `frontend/components/wiki/WikiTabInProjectStudio.tsx`
**Purpose:** Wiki tab in Project Studio
- **Size:** 150 LOC
- **Props:**
  ```typescript
  projectId: string
  projectName: string
  ```
- **Features:**
  - 4 tabs: Dashboard, Search, Browse, Ingest
  - Tab navigation with active state
  - Full component integration
  - Persistent tab selection
- **Integration:** Add to Project Studio sidebar tabs

#### 10. `frontend/components/wiki/WikiArtifactSection.tsx`
**Purpose:** Run artifacts display
- **Size:** 180 LOC
- **Props:**
  ```typescript
  runId: string
  projectId: string
  runName?: string
  ```
- **Features:**
  - List artifacts from run
  - Shows ingestion status
  - Links to artifact pages
  - Quick action buttons
  - Empty state messaging
- **API:** `GET /api/wiki/project/artifacts?run_id=...`
- **Integration:** Add to Run Studio artifacts section

#### 11. `frontend/components/wiki/WikiMemoryLink.tsx`
**Purpose:** Memory items linked to wiki
- **Size:** 280 LOC
- **Props:**
  ```typescript
  memoryId: string
  memoryType: 'fact' | 'decision' | 'constraint'
  memoryContent: string
  projectId: string
  ```
- **Features:**
  - Shows linked wiki pages
  - Create wiki page modal
  - Category selection
  - Source content preview
  - Type icons (fact/decision/constraint)
- **API:** `GET /api/wiki/project/memory/{memoryId}/pages`
- **Integration:** Add to Memory item detail view

#### 12. `frontend/components/wiki/CoordinatorWikiContext.tsx`
**Purpose:** Wiki context for planning
- **Size:** 280 LOC
- **Props:**
  ```typescript
  projectId: string
  runObjective: string
  runType?: string
  ```
- **Features:**
  - Auto-fetch relevant pages
  - Group by context type (Learning/Practice/Template)
  - Relevance score display
  - Expandable snippets
  - Add to plan buttons
  - Real-time updates
- **API:** `GET /api/wiki/project/context?question=...`
- **Integration:** Add to Coordinator planning UI

### Barrel Export

#### `frontend/components/wiki/index.ts`
**Purpose:** Central export for all components
- **Exports:** All 12 wiki components
- **Usage:** `import { WikiDashboard, WikiSearch, ... } from '@/components/wiki'`

---

## Documentation

### 1. `frontend/components/wiki/README.md`
**Purpose:** Component documentation and usage guide
- **Size:** 400 LOC
- **Sections:**
  - Component overview
  - Props interfaces
  - Features list
  - Usage examples
  - Integration points
  - Styling notes
  - API integration reference
  - Error handling
  - Performance notes
  - Testing patterns
  - Future enhancements

### 2. `WIKI_IMPLEMENTATION_SUMMARY.md`
**Purpose:** Complete project summary
- **Size:** 600 LOC
- **Sections:**
  - Project overview
  - Completion status by phase
  - Architecture overview
  - Test coverage summary
  - File listing with stats
  - Key features checklist
  - Deployment readiness
  - Success criteria

### 3. `WIKI_ARCHITECTURE.md`
**Purpose:** Visual architecture diagrams
- **Size:** 500 LOC
- **Sections:**
  - High-level system architecture
  - Backend service architecture
  - Frontend component architecture
  - Data flow diagrams (ingest/query/lint)
  - Integration points
  - Bidirectional learning flow
  - Technology stack

### 4. `WIKI_FILE_REFERENCE.md`
**Purpose:** This file - quick reference guide
- **Size:** 800 LOC
- **Sections:**
  - File listing with purposes
  - Backend service details
  - Frontend component details
  - Documentation overview
  - Quick reference tables

---

## File Statistics

### Backend
- **Total Files:** 6
- **Total Lines:** ~2,500
- **Test Files:** 6
- **Test Lines:** ~1,400
- **Coverage:** 147 tests

### Frontend
- **Total Files:** 13 (12 components + 1 barrel)
- **Total Lines:** ~5,500
- **TypeScript/React:** 5,000+ LOC
- **Documentation:** 500 LOC

### Documentation
- **Total Files:** 4
- **Total Lines:** ~2,300
- **Diagrams:** ASCII art (no external dependencies)

### Total Project
- **Files Created:** 23
- **Lines of Code:** ~10,300
- **Tests:** 147
- **Documentation Pages:** 4

---

## Quick Access by Feature

### I want to...

**Understand the system architecture**
→ Read `WIKI_ARCHITECTURE.md`

**See what's been implemented**
→ Read `WIKI_IMPLEMENTATION_SUMMARY.md`

**Use a component in my code**
→ Read `frontend/components/wiki/README.md`

**Implement a backend feature**
→ Check `backend/app/services/wiki_*.py`

**Add a new REST endpoint**
→ Edit `backend/app/api/wiki.py`

**Find a specific component**
→ Use this file: `WIKI_FILE_REFERENCE.md`

**Understand the data model**
→ Check `backend/app/db/wiki_models.py`

---

## Testing Quick Reference

### Run Backend Tests
```bash
# All tests
pytest backend/app/tests/test_wiki_*.py -v

# Specific phase
pytest backend/app/tests/test_wiki_operations.py    # Phase 1
pytest backend/app/tests/test_wiki_corrections.py   # Phase 2
pytest backend/app/tests/test_wiki_qa.py            # Phase 3
pytest backend/app/tests/test_wiki_integration.py   # Phase 4
pytest backend/app/tests/test_wiki_api.py           # Phase 4.5
```

### Test Coverage
- Phase 1: 24 tests ✅
- Phase 2: 33 tests ✅
- Phase 3: 21 tests ✅
- Phase 4: 30 tests ✅
- Phase 4.5: 39 tests ✅
- **Total:** 147 tests ✅

---

## API Endpoints Quick Reference

| Method | Endpoint | Purpose | File |
|--------|----------|---------|------|
| POST | `/wiki/{type}/ingest` | Add sources | `wiki_operations.py` |
| POST | `/wiki/{type}/query` | Answer questions | `wiki_qa.py` |
| POST | `/wiki/{type}/lint` | Health check | `wiki_qa.py` |
| GET | `/wiki/{type}/pages` | List pages | `wiki_integrations.py` |
| GET | `/wiki/{type}/search` | Search | `wiki_corrections.py` |
| GET | `/wiki/{type}/stats` | Dashboard stats | `wiki_integrations.py` |
| GET | `/health` | Service health | `wiki.py` |

---

## Component Hierarchy

```
WikiDashboard (entry point)
├─ WikiSearch
├─ WikiIngest
├─ WikiBrowse
│  └─ WikiPage
│     └─ WikiPagePreview
├─ WikiQuery
└─ WikiLint

WikiTabInProjectStudio
├─ WikiDashboard
├─ WikiSearch
├─ WikiIngest
└─ WikiBrowse

Integration Points:
├─ WikiArtifactSection (in Run Studio)
├─ WikiMemoryLink (in Memory items)
└─ CoordinatorWikiContext (in Coordinator)
```

---

**Reference Complete** ✅
**Ready for Phase 6** ✅
