# Wiki Schema & Conventions

Complete specification for wiki page structure, metadata, workflows, and configurations.

---

## 1. Page Structure & Format

### Frontmatter (YAML)
Every wiki page begins with YAML frontmatter enclosed in `---`:

```yaml
---
title: "Page Title"
category: "entity"  # entity | concept | comparison | template | synthesis | artifact | decision | learning
confidence: "high"  # high | medium | low
created_at: "2026-04-11T10:30:00Z"
updated_at: "2026-04-11T10:30:00Z"
created_by: "system"  # "system" for auto-generated, user email otherwise
source_count: 3
source_ids: ["mem_123", "run_456"]
linked_entities: ["DASH Framework", "Process Redesign"]
tags: ["finance", "transformation", "framework"]
version: 1
status: "published"  # published | draft | archived
---
```

### Required Frontmatter Fields
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| title | string | ✅ | Human-readable page title |
| category | enum | ✅ | Page type (entity, concept, etc.) |
| confidence | enum | ✅ | Data confidence (high/medium/low) |
| created_at | ISO8601 | ✅ | Creation timestamp |
| updated_at | ISO8601 | ✅ | Last update timestamp |
| created_by | string | ✅ | Creator identifier |
| source_count | int | ❌ | Number of sources used |
| source_ids | array | ❌ | Memory/run IDs that created this page |
| linked_entities | array | ❌ | Related entities mentioned |
| tags | array | ❌ | Searchable tags |
| version | int | ❌ | Page version number (for tracking) |
| status | enum | ❌ | Draft/published/archived |

### Page Body (Markdown)
After frontmatter, content is standard Markdown:

```markdown
## Overview
Brief description of the entity/concept.

## Definition
Formal definition or explanation.

## Key Points
- Point 1
- Point 2
- Point 3

## Related Concepts
- [Link to concept](concept_slug.md)
- [Another concept](another_concept.md)

## Best Practices
Steps, recommendations, or guidelines.

## Example
Real-world example or case study.

## References
- Source 1
- Source 2
- Source 3
```

### Heading Hierarchy
```
# H1 - Page Title (generated from frontmatter)
## H2 - Main Sections
### H3 - Subsections
#### H4 - Details (max depth)
```

---

## 2. Page Categories

### Entity Pages
**Purpose:** Describe a concept, framework, or methodology

**Frontmatter:**
```yaml
category: "entity"
confidence: "high"
linked_entities: ["Related Entity 1", "Related Entity 2"]
```

**Structure:**
1. Definition - What is it?
2. Origin - Where did it come from?
3. Key Components - What are the parts?
4. Applications - How is it used?
5. Related Entities - What else is related?

**Examples:**
- DASH Framework (from LP wiki)
- Financial Modeling Best Practices
- Process Redesign Patterns

---

### Concept Pages
**Purpose:** Explain an idea, principle, or theory

**Frontmatter:**
```yaml
category: "concept"
confidence: "medium"  # Concepts may have lower confidence
linked_entities: []
```

**Structure:**
1. Overview - Big picture
2. Core Idea - Main principle
3. Application - How to apply it
4. Limitations - When it doesn't apply
5. Related Concepts - Similar ideas

**Examples:**
- Variance Analysis
- Process Efficiency
- Change Management

---

### Comparison Pages
**Purpose:** Contrast two or more approaches

**Frontmatter:**
```yaml
category: "comparison"
linked_entities: ["Concept A", "Concept B"]
```

**Structure:**
```markdown
## Overview
What are we comparing and why?

## Concept A
- Characteristics
- Advantages
- Disadvantages
- Best used when...

## Concept B
- Characteristics
- Advantages
- Disadvantages
- Best used when...

## Comparison Table
| Aspect | Concept A | Concept B |
|--------|-----------|-----------|
| ...    | ...       | ...       |

## Recommendation
When to choose each approach
```

**Examples:**
- Lean vs Six Sigma
- Waterfall vs Agile
- Traditional vs Agile Finance

---

### Template Pages
**Purpose:** Reusable structures and formats

**Frontmatter:**
```yaml
category: "template"
confidence: "high"
tags: ["template", "reusable"]
```

**Content:**
Full template with placeholders:
```
[PLACEHOLDER: Project Name]
[PLACEHOLDER: Start Date]
[PLACEHOLDER: Team Members]

## Section 1
...
```

**Examples:**
- Financial Model Template
- Process Map Notation
- Executive Summary Template

---

### Synthesis Pages
**Purpose:** Cross-topic deep dives combining multiple sources

**Frontmatter:**
```yaml
category: "synthesis"
source_count: 5+
linked_entities: ["Entity 1", "Entity 2", "Entity 3"]
```

**Structure:**
```markdown
## Overview
Synthesis thesis statement

## Theme 1
How Entity 1 and Entity 2 relate

## Theme 2
How Entity 3 applies

## Integrated Framework
How it all comes together

## Case Study
Real-world application

## Next Steps
How to apply this synthesis
```

**Examples:**
- Building a CFO Intelligence Platform
- Integrated Finance Transformation Strategy
- Digital-First Financial Operations

---

### Artifact Pages
**Purpose:** Curated run outputs with context

**Frontmatter:**
```yaml
category: "artifact"
created_by: "system"  # Artifacts are auto-created from runs
source_ids: ["run_123"]
artifact_type: "model"  # model | analysis | deck | report | map
artifact_format: "xlsx"
```

**Structure:**
```markdown
## Overview
What this artifact is and why it matters

## Context
What run created it and why

## Key Findings
Main insights from the artifact

## How to Use
Instructions for using the artifact

## Related Artifacts
Other related outputs

## Associated Learning
What we learned from creating this
```

**Examples:**
- Financial Model v3
- Executive Presentation - Q2 Results
- Process Map - New Workflows

---

### Decision Pages
**Purpose:** Document important decisions and rationale

**Frontmatter:**
```yaml
category: "decision"
confidence: "high"
linked_entities: ["Technology", "Vendor", "Alternative"]
tags: ["decision", "technology"]
```

**Structure:**
```markdown
## Decision Statement
What we decided

## Problem Statement
What problem did we need to solve?

## Options Considered
1. Option A - Pros/Cons
2. Option B - Pros/Cons
3. Option C - Pros/Cons

## Chosen Solution
Why we chose this option

## Rationale
Key reasons for this decision

## Implementation Timeline
When and how we'll execute

## Risks & Mitigation
Potential risks and how we'll manage them

## Related Decisions
Other related decisions
```

**Examples:**
- Decision: Oracle over SAP
- Technology Choice: Salesforce
- Implementation: Phased Rollout vs Big Bang

---

### Learning Pages
**Purpose:** Capture insights and lessons learned

**Frontmatter:**
```yaml
category: "learning"
confidence: "high"
source_ids: ["run_123", "mem_456"]
tags: ["learning", "outcome"]
```

**Structure:**
```markdown
## What We Learned
Core insight or lesson

## Context
What situation or project generated this learning?

## Key Takeaways
- Takeaway 1
- Takeaway 2
- Takeaway 3

## How We'll Apply It
How will this inform future work?

## Related Learnings
Other insights in this domain

## Evidence
What data or examples support this learning?
```

**Examples:**
- Learning: Financial Model Accuracy Improved 23%
- Learning: Phased Implementation Reduces Risk
- Learning: Cross-functional Teams Accelerate Delivery

---

## 3. Naming & Slug Conventions

### File Naming
```
entity_DASH_Framework.md
concept_Variance_Analysis.md
comparison_Lean_vs_Six_Sigma.md
template_Financial_Model.md
synthesis_CFO_Platform.md
artifact_Financial_Model_v3.md
decision_Oracle_vs_SAP.md
learning_23_Percent_Accuracy_Gain.md
```

### Slug Format
- Replace spaces with underscores
- Remove special characters
- Use PascalCase for readability
- Lowercase for consistency
- Max 100 characters

**Valid Slugs:**
```
DASH_Framework
Variance_Analysis
Lean_vs_Six_Sigma
Financial_Model_Template
CFO_Intelligence_Platform
Oracle_Implementation
Process_Redesign_Best_Practices
```

---

## 4. Cross-References & Linking

### Internal Links (Markdown)
```markdown
[DASH Framework](./entities/DASH_Framework.md)
[See also: Process Redesign](./entities/Process_Redesign.md)
```

### Cross-Wiki Links (Project → LP)
```markdown
[DASH Framework](../leading_practices/entities/DASH_Framework.md)
[See LP Practice: Variance Analysis](...)
```

### Link Conventions
- Use relative paths for internal links
- Include link text that describes the relationship
- Link bidirectionally when possible
- Use "See also:" prefix for optional references

---

## 5. Metadata & Confidence Levels

### Confidence Scale
- **High (✓)** - Validated across 3+ sources, tested, proven
- **Medium (△)** - From 1-2 reliable sources, generally accepted
- **Low (?)** - Emerging idea, single source, under validation

### Source Tracking
Every page should track its sources:
```yaml
source_count: 3
source_ids: ["mem_123", "run_456", "external_source_789"]
```

### Versioning
Track changes over time:
```yaml
version: 2
version_history:
  - version: 1
    date: "2026-04-01"
    changes: "Initial creation"
  - version: 2
    date: "2026-04-11"
    changes: "Updated with new data"
```

---

## 6. Workflows

### Workflow 1: Ingest Source

**Trigger:** `POST /api/wiki/{wiki_type}/ingest`

**Steps:**
1. Source arrives (document, URL, run artifact, conversation)
2. **Tier 1 Retry:** Parse & extract (max 3 attempts)
3. **Tier 2 Auto-Correct:** Fix data quality
   - Validate frontmatter
   - Correct references
   - Normalize formatting
4. **Create/Update Pages**
   - Create entity pages from extracted concepts
   - Update index.md with new entries
   - Append to log.md with source metadata
5. **Optional Tier 3 QA**
   - Run health checks
   - Flag issues for review
   - Generate suggestions
6. **Return Results**
   ```json
   {
     "status": "success",
     "pages_created": 3,
     "pages_updated": 2,
     "corrections_made": [
       "Fixed missing frontmatter fields",
       "Normalized formatting"
     ],
     "qa_result": {
       "passed": true,
       "issues": []
     }
   }
   ```

---

### Workflow 2: Query Wiki

**Trigger:** `POST /api/wiki/{wiki_type}/query`

**Steps:**
1. User asks question
2. **Tier 1 Retry:** Search wiki index (max 3 attempts)
3. **Retrieve Pages**
   - Semantic search
   - Keyword matching
   - Category filtering
4. **Synthesize Answer**
   - LLM reads relevant pages
   - Traces source citations
   - Generates answer with references
5. **Tier 2 Auto-Correct**
   - Add missing citations
   - Flag stale references
   - Supplement with LP wiki (if project)
6. **Optional Tier 3 QA**
   - Evaluate answer completeness
   - Flag contradictions
   - Generate follow-up suggestions
7. **Return Answer**
   ```json
   {
     "answer": "...",
     "citations": [
       {
         "page_id": "entity_DASH_Framework",
         "title": "DASH Framework",
         "context": "..."
       }
     ],
     "confidence": "high",
     "qa_result": {
       "quality_score": 85,
       "issues": [],
       "suggestions": []
     }
   }
   ```

---

### Workflow 3: Lint/Health Check

**Trigger:** `POST /api/wiki/{wiki_type}/lint?auto_fix=true|false`

**Steps:**
1. **Run All Health Checks**
   - Contradictions: conflicting claims
   - Orphans: pages with no incoming links
   - Missing References: concepts without pages
   - Broken Links: references to non-existent files
   - Coverage Gaps: under-explored topics
   - Divergence: project vs LP alignment
   - Staleness: outdated pages

2. **Collect Issues**
   - Assign severity (low/medium/high)
   - List affected pages
   - Generate suggestions

3. **Optional Auto-Fix**
   - Fix formatting
   - Update broken references
   - Create stub pages

4. **Return Report**
   ```json
   {
     "passed": false,
     "issues_count": 5,
     "severity": "medium",
     "issues": [
       {
         "type": "orphan",
         "severity": "low",
         "title": "Page has no incoming links",
         "affected_pages": ["entity_XYZ"],
         "suggestion": "Link from related pages or delete"
       }
     ],
     "auto_fixes_applied": 2
   }
   ```

---

### Workflow 4: Promote to LP

**Trigger:** `POST /api/wiki/project/pages/{page_id}/promote`

**Steps:**
1. Project page author proposes promotion
2. **Create Proposal**
   - Page content
   - Rationale
   - Suggested category
3. **LP Review Queue**
   - Reviewer examines proposal
   - May request changes
4. **Approval Decision**
   - If approved: create LP page, add bidirectional links
   - If rejected: explain feedback to proposer
5. **Tracking**
   - LP page links back to original project page
   - Project page tracks promotion status
   - Both pages maintain source relationships

---

## 7. Integration Points

### Memory Items → Wiki
```python
# When memory item created/updated:
memory = MemoryItem(
    id="mem_123",
    type="decision",
    content="We chose Oracle over SAP"
)
# Auto-trigger:
wiki_ingest_from_memory(memory)
# Creates: entity_page or decision_page
```

### Run Artifacts → Wiki
```python
# When run completes:
run = Run(id="run_456", project_id="proj_123")
# Auto-trigger:
wiki_ingest_from_run(run)
# Creates: artifact_page, learning_page
```

### Conversations → Wiki
```python
# Monthly digest:
conversations = get_conversations_since(30_days_ago)
digest = create_digest(conversations)
# Auto-trigger:
wiki_ingest_from_conversation(digest)
# Creates: synthesis_page, learning_page
```

### Coordinator Planning
```python
# Before planning:
run = Plan(objective="Build financial model")
context = query_wiki_for_context(run.objective)
# Returns: relevant_pages with snippets
```

---

## 8. Tier Configurations

### Tier 1: Retry
```python
MAX_RETRY_ATTEMPTS = 3
EXPONENTIAL_BACKOFF_FORMULA = "min(1.5, 0.25 * 2^attempt)"

TRANSIENT_ERRORS = [
    TimeoutError,
    ConnectionError,
    ServiceUnavailableError,
    RateLimitError
]
```

### Tier 2: Auto-Correction
```python
AUTO_CORRECTION_ENABLED = True

CORRECTION_RULES = {
    "frontmatter": {
        "auto_fill_missing": True,
        "fix_invalid_values": True
    },
    "references": {
        "create_stubs": True,
        "update_broken": True
    },
    "formatting": {
        "normalize_lists": True,
        "standardize_headings": True
    },
    "data_types": {
        "convert_strings": True,
        "snap_enums": True
    },
    "duplication": {
        "detect_threshold": 0.75,
        "suggest_merge": True
    }
}
```

### Tier 3: QA
```python
QA_ENABLED = True
QA_SEVERITY_THRESHOLDS = {
    "low": (0, 1),      # 0 issues = low
    "medium": (1, 10),   # 1-9 issues = medium
    "high": (10, float('inf'))  # 10+ issues = high
}
```

---

## 9. Best Practices

### Writing Pages
1. **Be Clear** - Use simple, direct language
2. **Be Concise** - Say what matters, trim the rest
3. **Be Consistent** - Follow naming and structure conventions
4. **Be Complete** - Include examples, related concepts, references
5. **Be Current** - Update pages as situations change

### Page Quality
- **Minimum Length:** 300 words for entity pages
- **Maximum Depth:** 4 heading levels
- **Links Per Page:** 3-8 related pages
- **Update Frequency:** At least annually
- **Source Tracking:** Every claim should be traceable

### Managing Growth
- Archive pages that become obsolete
- Merge similar pages (with cross-references)
- Regularly review orphan pages
- Prune outdated content

---

## 10. Special Cases

### Archived Pages
Mark pages as archived instead of deleting:
```yaml
status: "archived"
archived_at: "2026-04-11T10:30:00Z"
archived_reason: "Superseded by [New Page Name]"
```

### Draft Pages
Work-in-progress pages:
```yaml
status: "draft"
draft_notes: "Still gathering sources..."
```

### External References
Links to external sources with attribution:
```markdown
[Deloitte Finance Transformation Framework](https://example.com/framework)
*Source: Deloitte Consulting*
```

---

## 11. Migration Guide (Existing Data)

### From Flat Leading Practices List
1. Categorize each practice (entity/concept/template/etc.)
2. Create wiki page with appropriate structure
3. Set confidence level based on validation
4. Add cross-references to related practices
5. Migrate to LP wiki `/leading_practices/` directory

### From Run Artifacts
1. Create artifact page with run metadata
2. Extract learnings into learning_page
3. Create decision_page for key choices
4. Link back to source run_id
5. Add to project wiki `/wiki/artifacts/` section

---

## 12. Example Pages

See `WIKI_SEED_CONTENT.md` for 5 example pages showing proper structure for:
- Entity Page (DASH Framework)
- Concept Page (Variance Analysis)
- Template Page (Financial Model Template)
- Decision Page (Oracle vs SAP)
- Learning Page (Process Redesign Success)

---

**Schema Version:** 1.0
**Last Updated:** 2026-04-11
**Status:** Active
