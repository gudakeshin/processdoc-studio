# Wiki System Architecture Diagram

## High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     WIKI SYSTEM - TWO LEVELS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 1: SOURCES (Immutable)                                         │   │
│  ├──────────────────────────────────────────────────────────────────────┤   │
│  │ • Uploaded Documents     • Web Articles     • Run Artifacts          │   │
│  │ • Conversations          • External Research • Project Outputs       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                        ↓                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 2: WIKI PAGES (LLM-Maintained)                                │   │
│  ├──────────────────────────────────────────────────────────────────────┤   │
│  │  ┌─────────────────────┐        ┌──────────────────────────────────┐│   │
│  │  │ Leading Practice    │        │ Project Wiki                     ││   │
│  │  │ Wiki (Global)       │        │ (Project-Scoped)                ││   │
│  │  │                     │        │                                  ││   │
│  │  │ • Frameworks        │        │ • Context (Background)           ││   │
│  │  │ • Methodologies     │        │ • Learnings (What Worked)        ││   │
│  │  │ • Templates         │        │ • Decisions (Why We Chose)       ││   │
│  │  │ • Case Studies      │        │ • Artifacts (Run Outputs)        ││   │
│  │  │ • Syntheses         │        │ • Linked Practices (LP Refs)     ││   │
│  │  │                     │        │                                  ││   │
│  │  │ PAGES:              │        │ PAGES:                           ││   │
│  │  │ • Entity Pages      │        │ • Entity Pages                   ││   │
│  │  │ • Comparisons       │        │ • Context Pages                  ││   │
│  │  │ • Syntheses         │        │ • Decision Pages                 ││   │
│  │  │ • Recommendations   │        │ • Artifact Catalogs              ││   │
│  │  └─────────────────────┘        └──────────────────────────────────┘│   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                  ↕           (Bidirectional Learning)              ↕         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 3: OPERATIONS (Cowork Tiers)                                  │   │
│  ├──────────────────────────────────────────────────────────────────────┤   │
│  │  Tier 1: Retry           Tier 2: Auto-Correct      Tier 3: QA/Lint │   │
│  │  • Exponential Backoff   • Fix Formatting          • 7 Health Checks│   │
│  │  • 3 Max Attempts        • Correct Data Types      • Issue Detection│   │
│  │  • Transient Detection   • Validate References     • Suggestions    │   │
│  │                          • Deduplicate Content     • Severity Calc  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Backend Service Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND SERVICES                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ wiki_operations.py - Core Orchestration                            │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │ • exponential_backoff()      • classify_error()                    │   │
│  │ • wiki_ingest_with_retry()   • wiki_query_with_retry()            │   │
│  │ • wiki_lint_with_retry()     • Helper functions (stub for Phase 2) │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                        ↓                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ wiki_corrections.py - Tier 2 Auto-Correction                        │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │ DataCorrector class methods:                                        │  │
│  │ • correct_frontmatter()         • correct_references()             │  │
│  │ • correct_formatting()          • correct_data_types()             │  │
│  │ • correct_duplication()         • correct_stale_references()       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                        ↓                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ wiki_qa.py - Tier 3 QA/Linting                                     │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │ WikiQAEvaluator class methods:                                      │  │
│  │ • _check_contradictions()      • _check_orphans()                  │  │
│  │ • _check_missing_references()  • _check_broken_links()             │  │
│  │ • _check_coverage_gaps()       • _check_divergence()               │  │
│  │ • _check_staleness()           • evaluate_wiki_health()            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                        ↓                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ wiki_integrations.py - System Integrations                          │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │ • WikiMemoryIntegration → Memory items to wiki                      │  │
│  │ • WikiRunIntegration → Run artifacts to wiki                        │  │
│  │ • WikiConversationIntegration → Conversation digests to wiki        │  │
│  │ • WikiCoordinatorIntegration → Wiki context for planning            │  │
│  │ • WikiLeadingPracticesIntegration → LP wiki retrieval & promotion   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                        ↓                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ wiki.py - REST API (FastAPI)                                        │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │ POST   /api/wiki/{wiki_type}/ingest                                 │  │
│  │ POST   /api/wiki/{wiki_type}/ingest/from-memory                     │  │
│  │ POST   /api/wiki/{wiki_type}/ingest/from-run                        │  │
│  │ POST   /api/wiki/{wiki_type}/ingest/from-conversation               │  │
│  │ POST   /api/wiki/{wiki_type}/query                                  │  │
│  │ GET    /api/wiki/{wiki_type}/context                                │  │
│  │ POST   /api/wiki/{wiki_type}/lint                                   │  │
│  │ GET    /api/wiki/{wiki_type}/pages                                  │  │
│  │ GET    /api/wiki/{wiki_type}/pages/{page_id}                        │  │
│  │ GET    /api/wiki/{wiki_type}/search                                 │  │
│  │ POST   /api/wiki/{wiki_type}/pages/{page_id}/promote                │  │
│  │ GET    /api/wiki/{wiki_type}/stats                                  │  │
│  │ GET    /health                                                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                        ↓                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ wiki_models.py - Data Models                                        │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │ • WikiPage          • WikiLog          • WikiIndex                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Frontend Component Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FRONTEND COMPONENTS (React/TS)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ CORE WIKI COMPONENTS                                               │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiDashboard                    📊 Statistics & Health    │   │   │
│  │  │ Total Pages | Pages This Week | Health Status | Stale Pages   │   │
│  │  │ Category Breakdown | Confidence Distribution | Health Alerts  │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiSearch                       🔍 Full-Text Search      │   │   │
│  │  │ Search Input | Category Filter | Confidence Filter       │   │   │
│  │  │ Results with Snippets | Facet Counts | Link to Pages     │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiIngest                       ⬆️ Source Ingestion      │   │   │
│  │  │ Source Type Selector | Dynamic Form Fields                │   │   │
│  │  │ Progress Tracking | Results Display | Corrections Summary │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiBrowse                       📖 Browse All Pages      │   │   │
│  │  │ Pagination | Sorting | Filtering | Summary Statistics      │   │   │
│  │  │ Pages List | Links to Details | Filter Sidebar             │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiPage                         📄 Single Page View      │   │   │
│  │  │ Content Tab | Links Tab | Metadata Tab                    │   │   │
│  │  │ Full Markdown Rendering | Cross-References | Frontmatter  │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiQuery                        ❓ Q&A Interface        │   │   │
│  │  │ Question Input | Answer Synthesis | Citations              │   │   │
│  │  │ Optional QA Evaluation | Related Questions | History       │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiLint                         ✓ Health Check UI        │   │   │
│  │  │ Issue Breakdown | Expandable Details | Suggestions         │   │   │
│  │  │ Auto-Fix Toggle | Severity Filtering | Actions             │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiPagePreview                  👁️ Inline Preview       │   │   │
│  │  │ Hover/Click Trigger | Smart Positioning | Quick Link       │   │   │
│  │  │ Summary + Metadata | Loading State | Error Handling        │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                        ↓                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ INTEGRATION COMPONENTS                                              │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiTabInProjectStudio           🗂️ Project Studio Tab    │   │   │
│  │  │ Embeds: Dashboard | Search | Browse | Ingest               │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiArtifactSection              📦 Run Artifacts Section │   │   │
│  │  │ Shows artifacts from run | Links to wiki pages             │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ WikiMemoryLink                   🔗 Memory Item Links     │   │   │
│  │  │ Shows wiki pages from memory | Create page modal            │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────┐   │   │
│  │  │ CoordinatorWikiContext           💡 Planning Context      │   │   │
│  │  │ Relevant pages for run objective | Grouped by type         │   │   │
│  │  └────────────────────────────────────────────────────────────┘   │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow: Ingest Operation

```
SOURCE
  ↓
[Parse Source]
  ↓ (Tier 1: With Retry)
[Extract Takeaways]
  ↓
[Create/Update Wiki Pages]
  ↓ (Tier 2: Auto-Correct)
  ├─ Fix Formatting
  ├─ Correct Data Types
  ├─ Validate References
  └─ Detect Duplicates
  ↓
[Update Index & Log]
  ↓
[Optional: Tier 3 QA]
  ├─ Check Contradictions
  ├─ Check Orphans
  ├─ Check Coverage Gaps
  └─ Generate Suggestions
  ↓
RESPONSE
{
  status: "success",
  pages_created: N,
  pages_updated: N,
  corrections_made: [],
  qa_result: {...}
}
```

## Data Flow: Query Operation

```
QUESTION
  ↓
[Search Wiki Index]
  ↓ (Tier 1: With Retry)
[Retrieve Relevant Pages]
  ↓
[Synthesize Answer]
  ↓
[Tier 2: Auto-Correct]
  ├─ Add Missing Citations
  ├─ Flag Stale References
  └─ Supplement with LP Wiki (if project)
  ↓
[Optional: Tier 3 QA]
  ├─ Evaluate Answer Quality
  ├─ Flag Coverage Gaps
  └─ Suggest Follow-ups
  ↓
RESPONSE
{
  answer: "...",
  citations: [...],
  source_pages: [...],
  confidence: "high",
  qa_result: {...}
}
```

## Data Flow: Lint Operation

```
WIKI
  ↓
[Run All Health Checks]
  ├─ Check Contradictions
  ├─ Check Orphans
  ├─ Check Missing References
  ├─ Check Broken Links
  ├─ Check Coverage Gaps
  ├─ Check Divergence (Project only)
  └─ Check Staleness
  ↓
[Collect Issues]
  ├─ Severity Calculation
  ├─ Affected Pages
  └─ Suggestions
  ↓
[Optional: Auto-Fix]
  ├─ Format Normalization
  ├─ Broken Link Removal
  └─ Reference Updates
  ↓
RESPONSE
{
  passed: bool,
  issues_count: N,
  issues: [...],
  severity: "high",
  suggestions: [...],
  auto_fixes_applied: N
}
```

## Integration Points with ProcessDoc v2

```
ProcessDoc v2 Systems        Wiki System                    Data Flow
──────────────────────────────────────────────────────────────────────────

Memory Items ─────────────→ WikiMemoryIntegration ──────→ Wiki Pages
(Facts, Decisions)          (auto-ingest)                (Entity/Decision)

Run Events ──────────────→ WikiRunIntegration ────────→ Wiki Artifacts
(Completion, Outcomes)      (extract learnings)        (Learnings/Decisions)

Conversations ──────────→ WikiConversationIntegration → Wiki Digests
(Transcripts)              (extract decisions)         (Monthly summaries)

Coordinator ────────────→ WikiCoordinatorIntegration ─→ Context Pages
(Planning)                 (retrieve context)         (Best Practices)

Leading Practices ──────→ WikiLeadingPracticesIntegration → LP Wiki
(Global Frameworks)        (repository)                   (Frameworks/Templates)
```

## Bidirectional Learning Flow

```
Project Wiki                                    Leading Practice Wiki
──────────────────                              ──────────────────────

Project Learnings ──→ [Promotion Proposal] ──→ LP Review Queue
   ↓                                                    ↓
   │                                           [Manual Review]
   │                                                    ↓
   │                                         [Approved/Rejected]
   │                                                    ↓
   │← ────────← ────[Backlink if Approved]← ────────
   
        Create LP Page
        Record Source
        Track Usage
```

## Component Data Dependencies

```
WikiDashboard
├─ GET /api/wiki/{wiki_type}/stats
└─ Display: total_pages, health, categories, confidence

WikiSearch
├─ GET /api/wiki/{wiki_type}/search?q=...
└─ Display: results, facets, categories, confidence

WikiIngest
├─ POST /api/wiki/{wiki_type}/ingest
├─ Tier 1: Retry with exponential backoff
├─ Tier 2: Auto-correction
├─ Tier 3: QA evaluation (optional)
└─ Display: pages_created, corrections, qa_results

WikiBrowse
├─ GET /api/wiki/{wiki_type}/pages?sort=...&filter=...
├─ Pagination, sorting, filtering
└─ Display: pages_list, pagination_info

WikiPage
├─ GET /api/wiki/{wiki_type}/pages/{page_id}
├─ Markdown content, metadata, links
└─ Display: content, tabs (content/links/metadata)

WikiQuery
├─ POST /api/wiki/{wiki_type}/query
├─ Tier 1: Retry, Tier 2: Auto-correct, Tier 3: QA (optional)
└─ Display: answer, citations, qa_score

WikiLint
├─ POST /api/wiki/{wiki_type}/lint
├─ 7 health checks, issue detection, suggestions
└─ Display: issues, severity, suggestions, auto_fixes

WikiPagePreview
├─ GET /api/wiki/{wiki_type}/pages/{page_id}/preview
├─ Lazy load on hover/click
└─ Display: summary, metadata, link
```

## Technology Stack

```
Frontend
├─ React 18+
├─ TypeScript 5+
├─ Next.js 13+ (routing)
├─ TailwindCSS 3+ (styling)
├─ Hooks API (state management)
└─ Fetch API (HTTP client)

Backend
├─ Python 3.10+
├─ FastAPI (REST API)
├─ SQLAlchemy (ORM)
├─ Pydantic (data validation)
└─ Standard Library (retry logic)

Testing
├─ Jest (frontend)
├─ React Testing Library (components)
├─ Pytest (backend)
└─ Fixtures/Mocks (test data)

Database
├─ PostgreSQL (production)
├─ SQLite (development)
└─ Migrations (schema versioning)
```

---

**Architecture Status:** Complete ✅
**Ready for Phase 6:** Yes ✅
