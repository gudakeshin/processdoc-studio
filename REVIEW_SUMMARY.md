# PPT Quality Review & System Diagnostics — Summary

**Reviewed Deck**: TestEng2_Executivedeck_20260408.pptx  
**Overall Assessment**: ⚠️ **Not Acceptable** — 6 of 9 slides are blank; zero data visualization

---

## What a Deloitte Consultant Would Say

### The Verdict (Grade: D-)

This deck **fails to meet basic executive communication standards**. While the slide structure is logical and some process details are accurate, the execution is severely broken:

- ❌ **6 of 9 slides are visually empty** (titles only, no content)
- ❌ **Zero data visualization** (no charts, tables, stat cards, diagrams anywhere)
- ❌ **No executive narrative** (no "why you should care," no value framing)
- ❌ **Text truncation** in content slides (descriptions cut off mid-sentence)
- ❌ **Cannot be presented to C-suite** (no metrics, no context, no decision-making framework)

### What's Working (30%)
- ✓ Logical slide ordering
- ✓ Appropriate slide titles (follow Deloitte P2P template)
- ✓ Some detail present in slides 5, 8, 9 (role descriptions, risks, next actions)
- ✓ Branding applied (green header bar, styling)
- ✓ Accurate system references (ME51N, MIGO, F110 are real SAP tcodes)

### What's Broken (70%)
| Issue | Impact |
|-------|--------|
| 6 blank slides (2, 3, 4, 6, 7) | Executive can't assess process scale, complexity, or value |
| Zero visuals | No charts, tables, stat cards, or visual process flows |
| Text truncation | Incomplete descriptions; unprofessional appearance |
| No metrics | No KPIs, baselines, targets, or quantified value case |
| No narrative flow | Slides jump around; gaps between logical sections |

---

## Why This Is Happening (Root Cause)

The generation system has **three critical failures**:

### Failure 1: PPTX Agent Not Receiving Required Data

**Current state**: Agent generates slides from user instruction + prior artifact text, without structured data

**What should happen**: Agent receives ProcessModel analytics pre-extracted by coordinator

```
What Agent Needs          What Agent Actually Gets
─────────────────────     ──────────────────────
Steps: 14                 User said: "executive deck"
Roles: [5 list]           Prior text: "...14 steps mentioned..."
Metrics: $450M spend      ProcessModel: Raw dict (not parsed)
KPI targets: X→Y          Assembled context: Retrieved context
Pillar defs: [3 list]     (Missing ProcessModel analytics)
Risk list: [6 items]      ↓
                          Agent struggles to extract data
                          → Falls back to title-only slides
```

**Fix**: Implement ContentEnrichmentEngine to extract metrics **once** at coordinator level, pass to all agents

### Failure 2: PPTX Agent Defaulting to Safe Fallback

**Current behavior**: 
- Agent intended to generate stat_cards (3 metric cards) for slide 2
- Agent couldn't confidently extract data (missing context)
- Agent generated: `{"slide_type": "stat_cards", "title": "...", "cards": []}`
- Renderer received empty cards → rendered title only

**Why**: Prompt instructs agent to "generate slide_type: stat_cards" but **doesn't provide the data** to fill them

**Fix**: Inject structured data into agent prompt
```python
# Current (fails)
user_prompt = f"""Generate slide 2 as stat_cards.
User instruction: {ctx.user_instruction}
Prior artifact: {ctx.prior_artifacts_excerpt}"""

# Fixed (succeeds)
user_prompt = f"""Generate slide 2 as stat_cards with these 3 cards:
- Card 1: Stat "14", Label "Steps", Description "End-to-end procurement process"
- Card 2: Stat "5", Label "Roles", Description "Procurement, Finance, Stores, Treasury, Vendors"
- Card 3: Stat "$450M", Label "Annual Spend", Description "High-volume P2P span across organization"

Return JSON: {{"slide_type": "stat_cards", "title": "...", "cards": [...]}}"""
```

### Failure 3: Renderer Doesn't Validate or Alert on Missing Data

**Current behavior**: System silently accepts empty data structures

```python
# Renderer receives:
{"slide_type": "stat_cards", "cards": []}  # Empty!

# Current behavior:
if cards:  # [] is falsy
    skip rendering
# Result: Blank slide, no error logged, no warning to user

# Better behavior:
if not cards:
    logger.error("Slide 2 has no stat_cards data")
    raise ValueError("Cannot render stat_cards without data")
```

**Fix**: Add validation that flags missing data and fails loudly

---

## How to Fix This Deck (Immediate)

### Priority 1: Enhance PPTX Agent Context

**File**: `/backend/app/agents/subagents.py::run_pptx_agent()` lines 1711–1724

Add structured data extraction:

```python
def run_pptx_agent(ctx: AgentContext, ...):
    # BEFORE: Pass raw process_model to Claude
    # AFTER: Extract key metrics and pass explicitly
    
    # Extract from ProcessModel
    steps_count = len(ctx.process_model.get("steps", []))
    roles = list(set(s.get("owner") for s in ctx.process_model.get("steps", [])))
    systems = extract_systems(ctx.process_model)
    cycle_time = ctx.process_model.get("metadata", {}).get("cycle_time", "14 days")
    spend = ctx.process_model.get("metadata", {}).get("span", "$450M annual")
    
    # Define pillars (for slide 3)
    pillars = extract_pillars(ctx.process_model)  # e.g., ["Governance", "Quality", "Productivity"]
    
    # Extract risks (for slide 8)
    risks = extract_risks(ctx.process_model)[:6]
    
    # Build enhanced prompt with data
    user_prompt = f"""
    {ctx.user_instruction}
    
    PROCESS ANALYTICS (use for slides):
    - Slide 2 (stat_cards): {steps_count} steps, {len(roles)} roles, {len(systems)} systems, {spend} span
    - Slide 3 (column_cards): {len(pillars)} pillars: {', '.join(pillars)}
    - Slide 4 (stack_layers): Key workflow phases: [extract from model]
    - Slide 6 (table): {steps_count} steps with owners: {format_steps(ctx.process_model)}
    - Slide 7 (stat_cards): Current cycle time: {cycle_time}, Target: X days (calculate from model)
    - Slide 8 (bullets): Top {len(risks)} risks: {format_risks(risks)}
    
    Prior narrative context: {ctx.prior_artifacts_excerpt[:2800]}
    """
    
    # Rest of prompt generation
    system_prompt = PPTX_SYSTEM_PROMPT  # Unchanged
    pptx_json = claude.generate(system_prompt, user_prompt)
    return pptx_json
```

### Priority 2: Improve PPTX Agent Prompt

**File**: `/backend/app/agents/subagents.py::run_pptx_agent()` system prompt (lines 1950–2000)

Add explicit data templates:

```
MANDATORY SLIDE SEQUENCE (with data templates):

1. TITLE SLIDE
   - Title: [Process name]
   - Subtitle: [Executive value prop, e.g., "Enable 50% faster P2P cycle"]
   - Badges: [Up to 4 value claims, not just metrics]

2. STAT_CARDS (Must have exactly 3 cards)
   - Card 1: Stat=[X], Label=[Y], Description=[Why this matters]
   - Card 2: Stat=[X], Label=[Y], Description=[Why this matters]
   - Card 3: Stat=[X], Label=[Y], Description=[Why this matters]
   - Example provided: {provided_metrics_json}

3. COLUMN_CARDS (Must have exactly 3 columns)
   - Column 1: Title=[Pillar 1], Body=[Why important, 1-2 sentences]
   - Column 2: Title=[Pillar 2], Body=[Why important, 1-2 sentences]
   - Column 3: Title=[Pillar 3], Body=[Why important, 1-2 sentences]

... (continue for all slide types)
```

### Priority 3: Add Validation to Renderer

**File**: `/backend/app/services/storage.py::_write_pptx_output()` lines 378–759

```python
def _render_stat_cards(prs, slide_json):
    cards = slide_json.get("cards", [])
    
    if not cards:
        logger.error(
            f"Slide '{slide_json.get('title')}' has no stat_cards data. "
            f"Expected 3 cards, got {len(cards)}."
        )
        # Option 1: Raise error to trigger regeneration
        raise ValueError("Stat cards data missing")
        
        # Option 2: Create placeholder
        # cards = [{"stat": "[TBC]", "label": "[Title TBC]", "description": "[Data required]"}] * 3
```

### Priority 4: Fix Text Truncation

**File**: `/backend/app/services/storage.py::_render_bullets()` etc.

```python
def _render_bullets(prs, slide_json):
    slide = prs.slides.add_slide(...)
    
    bullets = slide_json.get("bullets", [])
    
    # Validate text length before rendering
    max_chars_per_bullet = 120  # Adjust based on font size
    
    for i, bullet in enumerate(bullets):
        if len(bullet) > max_chars_per_bullet:
            logger.warning(
                f"Bullet {i} on slide '{slide_json['title']}' is {len(bullet)} chars "
                f"(max {max_chars_per_bullet}). May be truncated."
            )
            # Option: Truncate with ellipsis
            # bullet = bullet[:max_chars_per_bullet - 3] + "..."
    
    # ... rest of rendering
```

---

## How to Fix the System (Long-Term)

The immediate fixes above will unblock this deck. But the **architectural issues** affect all output types.

From **ARCHITECTURAL_REVISION_FRAMEWORK.md**:

### Architecture Fix 1: Content Enrichment Engine
**What**: Build ProcessModel analytics **once** at coordinator level, pass to all agents

**Files to create**: `/backend/app/services/content_enrichment.py`

**Benefit**: PPTX, DOCX, PDF, Narrative all get same enriched context automatically

### Architecture Fix 2: Deliverable Abstraction
**What**: All output types implement `IDeliverable` interface

**Files to create**: `/backend/app/core/deliverable*.py`

**Benefit**: New output types inherit branding, quality checks, validation from framework

### Architecture Fix 3: Unified Quality Framework
**What**: Quality rules apply to all types, not output-type-specific

**Files to create**: `/backend/app/core/quality_framework.py`

**Benefit**: Narrative coherence, branding compliance, content quality checked uniformly

---

## Documents Created

Three comprehensive documents have been saved:

1. **DECK_QUALITY_REVIEW_DELOITTE.md**
   - Scathing but detailed quality review from Deloitte consultant perspective
   - Grade: D- (Below acceptable standard)
   - 70% of content is broken, 30% is working
   - What's working, what's not, recommended fixes

2. **SYSTEM_DIAGNOSTICS_PPT_FAILURE.md**
   - Technical root cause analysis
   - Maps deck failures to specific code locations
   - 4 failure points with code examples
   - Immediate fixes + long-term architectural improvements

3. **ARCHITECTURAL_REVISION_FRAMEWORK.md**
   - Proposes unified framework for all deliverables
   - 5 core abstractions (Deliverable, Branding Service, Quality Framework, Enrichment Engine, Context)
   - Pluggable architecture so new output types inherit improvements
   - 3-phase implementation roadmap (8–12 weeks)

---

## Bottom Line

**The current PPT generation is broken.** But it's **fixable without architectural change** (Priority 1–4 above, 1–2 weeks effort).

However, **the root cause is architectural** — data enrichment and quality logic scattered across output types. The ARCHITECTURAL_REVISION_FRAMEWORK.md proposes a unified solution that prevents this failure from recurring and scales improvements across all deliverables.

**Recommendation**:
1. **Immediately** apply Priority 1–4 fixes to unblock this deck
2. **Plan Phase 1** of architectural revision (Deliverable abstraction + Branding Service) in parallel
3. **By end of Q2** have generalized framework so all improvements apply to all types

---

**Next Step**: Review SYSTEM_DIAGNOSTICS_PPT_FAILURE.md with the dev team to identify which fixes to apply first.
