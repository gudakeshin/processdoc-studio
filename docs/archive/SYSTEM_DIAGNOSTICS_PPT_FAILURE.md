# System Diagnostics: Why PPT Generation is Failing

**Date**: 2026-04-08  
**Analyzed File**: TestEng2_Executivedeck_20260408.pptx  
**Diagnosis**: Generation system has critical failures at multiple levels

---

## Quick Summary

The generated deck reveals **three critical system failures**:

1. **Content Generation Failure** — PPTX agent not generating slide content (stat cards, columns, tables)
2. **Data Enrichment Failure** — Agent not receiving ProcessModel metrics/context
3. **Rendering Incomplete** — Some slides render only titles, missing data payloads

**Impact**: 6 of 9 slides are blank; zero visual content; unexecutable for C-suite

---

## Failure Point 1: PPTX Agent Not Generating Varied Slide Types

### Expected Flow
```
PPTX Agent receives instruction
  ↓
Agent generates JSON with 8 slide types:
  - title (slide 1)
  - stat_cards (slide 2) ← Should have 3 metric cards
  - column_cards (slide 3) ← Should have 3 pillar cards
  - stack_layers (slide 4) ← Should have workflow layers
  - bullets (slide 5) ← Has content ✓
  - table (slide 6) ← Should have step-by-step table
  - stat_cards (slide 7) ← Should have metric cards
  - bullets (slide 8) ← Has content ✓
  - bullets (slide 9) ← Has content ✓
  ↓
Renderer outputs PPTX with all visual variety
```

### Actual Flow
```
PPTX Agent receives instruction
  ↓
Agent generates JSON with titles only:
  - title (slide 1) ✓
  - [missing stat_cards data] → Falls back to title-only (slide 2) ✗
  - [missing column_cards data] → Falls back to title-only (slide 3) ✗
  - [missing stack_layers data] → Falls back to title-only (slide 4) ✗
  - bullets (slide 5) ✓
  - [missing table data] → Falls back to title-only (slide 6) ✗
  - [missing stat_cards data] → Falls back to title-only (slide 7) ✗
  - bullets (slide 8) ✓
  - bullets (slide 9) ✓
  ↓
Renderer outputs text-only PPTX
```

### Root Cause

**File**: `/backend/app/agents/subagents.py::run_pptx_agent()` (lines 1950–2085)

**Current Logic** (pseudocode):
```python
def run_pptx_agent(ctx):
    system_prompt = """
    Generate a JSON with slides.
    Slide types: title, bullets, stat_cards, column_cards, stack_layers, table, chart, section_divider
    Mandatory sequence:
    1. Title slide
    2. Stat cards (3 KPIs)
    3. Column cards (3 pillars)
    4. Stack layers (workflow)
    5. Bullets (role mandates)
    6. Table (step-by-step)
    7. Stat cards (metrics)
    8+ Bullets (risks, actions)
    """
    
    user_prompt = f"""
    {ctx.user_instruction}
    
    Prior narrative: {ctx.prior_artifacts_excerpt[:2800]}
    """
    
    pptx_json = claude.generate(system_prompt, user_prompt)
    return pptx_json
```

**Problems with this approach**:

1. **No data passed to Claude for slides 2, 3, 4, 6, 7**
   - Slide 2 (stat_cards) needs: step count, role count, system count, span of spend
   - Slide 3 (column_cards) needs: 3 pillar definitions (Governance, Quality, Productivity)
   - Slide 4 (stack_layers) needs: workflow phase definitions
   - Slide 6 (table) needs: actual process steps with owners
   - Slide 7 (stat_cards) needs: KPI baseline + target values

   **But Claude receives**: Only user instruction + prior artifact text (no structured ProcessModel data)

2. **No explicit instructions for content population**
   - Prompt says "generate slide_type: stat_cards" but **doesn't show what data to put in cards**
   - Claude defaults to: "Create a JSON with slide type stat_cards, but I don't have the data, so I'll just put a title"

3. **Fallback behavior is silent**
   - System doesn't error when stat_cards JSON is missing data
   - Renderer receives: `{"slide_type": "stat_cards", "title": "...", "cards": []}`
   - Renderer outputs: Blank slide with title only (no error flagged)

---

## Failure Point 2: Data Enrichment Not Passed to PPTX Agent

### What's Missing from Agent Context

The PPTX agent should receive (but doesn't):

```python
# WHAT SHOULD BE IN ctx

class ProcessAnalytics:
    steps_count: int           # 14
    roles: list[str]           # [Procurement, Finance, Stores, Treasury, ...]
    decision_points: int       # 2
    handoffs: int              # 4
    systems: list[str]         # [SAP, HDFC Portal, Email, Excel]
    cycle_time_current: str    # "14 days"
    error_rate: float          # 0.08
    span_of_spend: str         # "$450M annual"

ctx.enrichment.process_analytics = ProcessAnalytics(...)

# Pillar definitions
ctx.enrichment.process_pillars = {
    "governance": "Centralized vendor master; approval controls",
    "quality": "QM integration; material inspection before GRN",
    "productivity": "Straight-through processing; OCR + DMEE automation"
}

# Risk profile
ctx.enrichment.risks = [
    {"gap": "Vendor Master Governance", "impact": "high", "detail": "~300 duplicate codes"},
    {"gap": "GRN Timing Misalignment", "impact": "high", "detail": "2–3 day lag"},
    ...
]
```

### Current Agent Context

```python
# WHAT ACTUALLY IS IN ctx (for PPTX agent)

ctx = AgentContext(
    output_type="pptx",
    user_instruction="Generate an executive deck for Procure-to-Pay process",
    process_model={...},           # Raw ProcessModel dict (not parsed/enriched)
    assembled_context="...",       # Tiered retrieval context (not ProcessModel analytics)
    prior_artifacts_excerpt="...", # Snippet of prior narrative (no structured data)
    # NO: process_analytics
    # NO: process_pillars
    # NO: risk_profile
    # NO: value_drivers
)

# PPTX agent must extract all this from unstructured text
# If it fails, slide types that need data (stat_cards, columns, tables) come out empty
```

### Why This Matters

**Slide 2 generation**:

Claude receives:
```
Generate slide_type: stat_cards with 3 cards

User said: "executive deck for procure-to-pay"
Prior artifact: "[excerpt about P2P process structure]"
ProcessModel: {steps: [...], roles: [...], ...}
```

Claude tries to infer:
- How many steps? (Searches prior artifact... finds "14 steps" in prose)
- How many roles? (Searches prior artifact... finds "5 roles" in prose)
- Span of spend? (Not in context, so Claude might guess "$500M")

If extraction fails or Claude is uncertain:
```python
# Claude generates this fallback JSON:
{
    "slide_type": "stat_cards",
    "title": "P2P Process Scale & Scope",
    "cards": []  # EMPTY because Claude couldn't confidently extract data
}
```

Renderer receives empty cards array → renders title only.

---

## Failure Point 3: Renderer Doesn't Validate or Error on Empty Data

### Current Rendering Logic

**File**: `/backend/app/services/storage.py::_write_pptx_output()` (lines 378–759)

```python
def _write_pptx_output(state, pptx_slides_json, ...):
    prs = Presentation(...)
    
    for slide_json in pptx_slides_json["slides"]:
        slide_type = slide_json["slide_type"]
        
        if slide_type == "stat_cards":
            _render_stat_cards(prs, slide_json)
        elif slide_type == "column_cards":
            _render_column_cards(prs, slide_json)
        # etc.

def _render_stat_cards(prs, slide_json):
    slide = prs.slides.add_slide(...)
    
    # Add title
    title_shape = slide.shapes.add_textbox(...)
    title_shape.text = slide_json["title"]  # ✓ This renders
    
    # Add cards
    cards = slide_json.get("cards", [])  # If cards is []...
    if not cards:  # Silent fallback!
        # No error, no warning, just skip card rendering
        pass
    
    for i, card in enumerate(cards):
        # Render card (never executed if cards is empty)
        ...
```

**Problem**: System silently accepts empty data

**Expected behavior**:
```python
def _render_stat_cards(prs, slide_json):
    cards = slide_json.get("cards", [])
    if not cards:
        # ERROR CASE: Alert that slide is empty
        logger.warning(f"Slide {slide_json['title']} has no stat_cards data")
        # Option 1: Raise error (forces regeneration)
        # Option 2: Create placeholder warning slide
        # Option 3: Log and let user know generation failed
```

**Actual behavior**:
```python
    # Silent skip → renders title-only slide → user sees blank slide
```

---

## Failure Point 4: Text Truncation in Slides 5, 8, 9

### What's Happening

**Slide 5** (from XML analysis):
```
Department Heads / Storesmen: Raise PRs in ME51N with material, quantity, required date, plant, and [TRUNCATED]
Finance Controller: Countersign PRs >INR 50K via email; approve invoices; oversee payment runs.
...
Treasury Team: Execute F110 payment proposals; initiate bank transfers via HDFC portal (manual); ema[TRUNCATED]
```

**Slide 8**:
```
Vendor Master Governance: ~300 duplicate codes; decentralized plant-level creation; no central stewa[TRUNCATED]
GRN Timing Misalignment: 2–3 day lag between physical receipt and SAP posting; inventory/AP visibili[TRUNCATED]
...
```

### Root Cause

**File**: `/backend/app/agents/subagents.py` (where agent generates text for slides 5, 8, 9)

Claude is generating text **longer than slide shape capacity**:

```python
# Agent generates:
bullet_text = """
Department Heads / Storesmen: Raise PRs in ME51N with material, quantity, required date, plant, and delivery schedule to manage procurement forecast
"""
# Length: ~140 characters

# PPTX rendering adds to shape:
shape.text = bullet_text  # ✓ Fits initially

# But when rendering to PPTX:
# - Font size auto-adjusts based on bullet count
# - Text wrapping rules apply
# - If text > available space: truncate or overflow

# Current behavior: TRUNCATE without warning
```

**Why**:

From `/backend/app/services/storage.py::_render_bullets()`:

```python
def _render_bullets(prs, slide_json):
    slide = prs.slides.add_slide(...)
    
    bullets = slide_json.get("bullets", [])
    
    # Auto-size font based on bullet count
    font_size = {
        3: 16, 4: 14, 5: 13, 6: 12, 7: 11, 8: 10, 9: 9, 10: 8
    }.get(len(bullets), 8)
    
    for bullet in bullets:
        p = shape.text_frame.add_paragraph()
        p.text = bullet
        p.font.size = Pt(font_size)
        # python-pptx auto-truncates if text > text_frame width
```

**The issue**: No validation that text fits before rendering

---

## Why Architectural Fixes Matter

This deck failure is **not just about PPTX quality**—it reveals systemic architectural issues that affect ALL output types:

### Issue 1: Data Enrichment Not Pre-Built
- **PPTX agent lacks ProcessModel metrics**
- **DOCX agent would have same problem** (no analytics, no risk extraction, no value drivers)
- **Narrative agent would struggle** (no intent classification, no audience context)

**Architectural Fix** (from ARCHITECTURAL_REVISION_FRAMEWORK.md):
```
Create ContentEnrichmentEngine that builds ONCE at coordinator level
  ↓
All agents receive enriched context (process_analytics, risk_profile, value_drivers)
  ↓
No duplicate context building, no missing data
```

### Issue 2: Output-Type-Specific Logic Scattered
- **PPTX rendering hardcoded in storage.py**
- **Quality checks hardcoded in visual_qa.py**
- **Branding hardcoded in storage.py**
- **New output type = duplicate all this logic**

**Architectural Fix**:
```
Create IDeliverable interface
  ↓
Each type implements: render(), validate(), apply_branding()
  ↓
Registry handles all types uniformly
```

### Issue 3: No Pluggable Quality Rules
- **PPTX visual QA** checks for chrome, density, etc.
- **DOCX quality** uses separate contract system
- **Narrative quality** uses different rubric
- **New quality dimension = must add to each type**

**Architectural Fix**:
```
Create QualityFramework with pluggable rules
  ↓
Rules apply to all types (NarrativeCoherenceRule, BrandingComplianceRule, etc.)
  ↓
New rule = single implementation, all types benefit
```

---

## System Improvement Priority

### IMMEDIATE (Fix This Deck)

1. **Enhance PPTX Agent Context**
   - Pass ProcessModel metrics to agent
   - Provide pillar definitions
   - Pass risk list with details
   - Supply KPI baseline + target values

   **File to modify**: `/backend/app/agents/subagents.py::run_pptx_agent()` (lines 1711–1724)

2. **Improve PPTX Agent Prompt**
   - Explicitly instruct Claude: "Slide 2 must have 3 stat cards with these metrics: [X, Y, Z]"
   - Provide data inline in prompt
   - Example:
     ```
     Slide 2 (stat_cards): Must have exactly 3 cards:
     - Card 1: "14" steps, "End-to-end procure, receipt, invoice, pay"
     - Card 2: "5" roles, "Procurement, Finance, Stores, Treasury, Vendors"
     - Card 3: "$450M" annual spend, "High-volume, multi-system P2P"
     ```

   **File to modify**: `/backend/app/agents/subagents.py::run_pptx_agent()` (lines 1950–2000)

3. **Add Validation to Renderer**
   - Check that each slide type has required data
   - If missing: error or fallback to placeholder
   - Log warnings so user knows slide is incomplete

   **File to modify**: `/backend/app/services/storage.py::_write_pptx_output()` (lines 437–759)

4. **Fix Text Truncation**
   - Validate text length before rendering
   - Either: truncate smartly with "..." + [See full version]
   - Or: reduce font size if needed
   - Or: spread content across multiple lines/shapes

   **File to modify**: `/backend/app/services/storage.py::_render_bullets()` etc.

### SHORT TERM (Fix the System)

5. **Implement ContentEnrichmentEngine** (Phase 3 of architectural revision)
   - Extract ProcessModel metrics once at coordinator level
   - Classify user intent (risk | value | capability | compliance)
   - Infer audience type
   - Pass to all agents via enhanced AgentContext

   **Files to create**: `/backend/app/services/content_enrichment.py`

6. **Enhance AgentContext**
   - Add enrichment field
   - Add convenience methods (get_audience_hints, get_risk_focus, etc.)

   **File to modify**: `/backend/app/agents/agent_types.py`

7. **Implement Deliverable Abstraction** (Phase 1 of architectural revision)
   - Create IDeliverable interface
   - All types implement uniform interface
   - Eliminates output-type-specific code in storage.py

   **Files to create**: `/backend/app/core/deliverable*.py`

---

## Success Criteria: What a Good PPT Should Have

After fixes, the next generated deck should have:

| Slide | Type | Status |
|-------|------|--------|
| 1 | title | ✓ Title + value prop |
| 2 | stat_cards | ✓ 3 metric cards with data |
| 3 | column_cards | ✓ 3 pillar columns with descriptions |
| 4 | stack_layers | ✓ Workflow layers showing roles/phases |
| 5 | bullets | ✓ Role mandates (complete, not truncated) |
| 6 | table | ✓ Step-by-step table with owners |
| 7 | stat_cards | ✓ Metric cards (current vs. target) |
| 8 | bullets | ✓ Risk/gap list with severity indicators |
| 9 | bullets | ✓ 3 next actions with timeline/owner |

**Visual Quality**:
- ✓ All slides have visual content (no blank slides)
- ✓ Color variety (stat cards, pillar colors rotate)
- ✓ No text truncation
- ✓ Readable font sizes
- ✓ Clear visual hierarchy

**Content Quality**:
- ✓ Metrics are accurate (sourced from ProcessModel)
- ✓ Risk list is complete (no mid-sentence cutoff)
- ✓ Next actions are specific (with timeline + owner + benefit)
- ✓ Narrative flows logically (each slide builds on prior)

---

## Conclusion

**The current PPT failure is a symptom of deeper architectural issues**:

1. ❌ Data enrichment not pre-built → Agents receive incomplete context
2. ❌ Output types hardcoded → Can't reuse logic across types
3. ❌ Quality rules scattered → No unified evaluation framework
4. ❌ No validation in renderers → Silent failures produce blank slides

**The ARCHITECTURAL_REVISION_FRAMEWORK.md proposes solutions** that would prevent this failure from happening in PPTX, DOCX, PDF, and future output types.

**For now**: Apply immediate fixes to PPTX agent + renderer to stop blank slides and text truncation.

**Long-term**: Implement architectural refactors so improvements scale across all deliverables.

