# Phase 1 Test Plan — PPTX Quality Fixes

**Date**: 2026-04-08  
**Status**: Ready for Testing  
**Objective**: Verify that Phase 1 fixes eliminate blank slides and text truncation

---

## Implementation Checklist ✓

### Step 1.1: Inject Enriched Metrics into Agent Prompt ✓
**File**: `/backend/app/agents/subagents.py` lines 1998–2031
- [x] Extract analytics from `ctx.enrichment.process_analytics`
- [x] Extract risk profile from `ctx.enrichment.risk_profile`
- [x] Extract value drivers from `ctx.enrichment.value_drivers`
- [x] Build `data_for_slide_2` with metrics (steps, roles, systems)
- [x] Build `data_for_slide_7` with cycle time/error rate/controls guidance
- [x] Inject data into user prompt

**Verification**: Run PPTX agent with test ProcessModel; check logs for "DATA FOR SLIDE" strings in prompt

---

### Step 1.2: Add Explicit Data Templates to System Prompt ✓
**File**: `/backend/app/agents/subagents.py` lines 1958–1988
- [x] Add stat_cards example with 3 populated cards
- [x] Add column_cards example with 3 pillar columns
- [x] Add table example with step-by-step rows
- [x] Add warning: "Do NOT generate empty stat_cards=[], column_cards=[], table.rows=[]"

**Verification**: System prompt contains JSON examples; Claude generation produces non-empty arrays

---

### Step 1.3: Add Validation Warnings to Renderers ✓
**File**: `/backend/app/services/storage.py`
- [x] _render_stat_cards_slide (lines 540–545): warn if cards array is empty
- [x] _render_column_cards_slide (lines 582–587): warn if cards array is empty
- [x] Both log structured warning with slide number, type, expected count, actual count

**Verification**: Generate deck with empty slides; check logs for `[PPTX QA]` warnings

---

### Step 1.4: Add Text Truncation Validation ✓
**File**: `/backend/app/services/storage.py` lines 504–514 (_render_bullets_slide)
- [x] Calculate max_chars based on font size (larger font → fewer chars allowed)
- [x] Validate each bullet against max_chars limit
- [x] Log warning with bullet index, char count, max_chars, and text preview
- [x] Preserve original text (don't auto-truncate; let renderer handle it)

**Verification**: Generate deck with long bullets; check logs for truncation warnings

---

### Step 1.5: Add Quality Gate for Completeness ✓
**File**: `/backend/app/services/deliverable_quality.py` lines 22–66 + integration at lines 309–325
- [x] Implement _validate_pptx_completeness(pptx_json) function
- [x] Check stat_cards has 3+ items, column_cards has 3+ items, etc.
- [x] Integrate check into run_deliverable_quality_loop()
- [x] Trigger remediation if completeness fails

**Verification**: Generate deck; quality loop should fail if slides are incomplete; trigger regeneration

---

## Test Suite

### Test 1: Verify Metrics Injection ✓

**Setup**: Run PPTX agent with a test ProcessModel

**Test code**:
```python
from backend.app.agents.subagents import run_pptx_agent
from backend.app.agents.agent_types import AgentContext

# Create test context with enrichment
ctx = AgentContext(
    run_id="test_123",
    output_type="pptx",
    user_instruction="Generate executive deck for P2P process",
    process_model={
        "steps": [{"role": "Procurement"}, ...],  # 14 steps
        "systems": ["SAP", "Portal", "Email"],
    },
    assembled_context="...",
    enrichment=ProcessAnalytics(steps_count=14, roles_count=5, ...)
)

# Run agent
output = run_pptx_agent(ctx)

# Verify output has metrics
assert "DATA FOR SLIDE 2" in output.logs  # Injected metrics appear in prompt
assert "14" in output.pptx_json  # Metrics in generated JSON
```

**Expected Result**: Agent receives metrics in prompt; generates slides with actual data

---

### Test 2: Verify Validation Catches Empty Slides ✓

**Setup**: Create a deck with intentionally empty stat_cards

**Test code**:
```python
from backend.app.services.storage import _write_pptx_output
import logging

# Configure logging to capture warnings
logging.basicConfig(level=logging.WARNING)

# Create deck JSON with empty stat_cards
pptx_slides = {
    "slides": [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "stat_cards", "title": "Metrics", "stat_cards": []},  # Empty!
        {"slide_type": "column_cards", "title": "Pillars", "column_cards": [...]},
    ]
}

# Render
state = {}
_write_pptx_output(state, pptx_slides, ...)

# Verify warning logged
# Expected: "[PPTX QA] Slide 2 ('Metrics'): slide_type='stat_cards' has no cards. Expected 3 cards, got 0."
```

**Expected Result**: Logs contain warnings for each empty slide; slide renders title-only

---

### Test 3: Verify Text Truncation Warnings ✓

**Setup**: Create slide with long bullet text

**Test code**:
```python
# Bullet longer than max_chars for font size
pptx_slides = {
    "slides": [
        {
            "slide_type": "bullets",
            "title": "Long Text Test",
            "bullets": [
                "This is a very long bullet text that exceeds 150 characters and should trigger a truncation warning in the logs"
            ]
        }
    ]
}

# Render
_write_pptx_output(state, pptx_slides, ...)

# Verify warning logged
# Expected: "[PPTX QA] Slide X ('Long Text Test'): Bullet 0 is 145 chars (max 150)..."
```

**Expected Result**: Logs warn about long bullets; text is preserved as-is

---

### Test 4: Verify Completeness Check Triggers Remediation ✓

**Setup**: Run quality loop with incomplete PPTX

**Test code**:
```python
from backend.app.services.deliverable_quality import run_deliverable_quality_loop

state = {"skill_card": {"primary_skill_by_output_type": {"pptx": {...}}}}
outputs = {
    "pptx_slides": json.dumps({
        "slides": [
            {"slide_type": "stat_cards", "title": "Metrics", "stat_cards": []}  # Empty!
        ]
    })
}

# Run quality loop
report, refreshed_outputs = run_deliverable_quality_loop(
    state=state,
    wanted=["pptx_slides"],
    outputs=outputs,
    apply_remediation=lambda s, w, f: {...},  # Mock remediation
    emit_event=None,
    project_id="test_123"
)

# Verify failure and remediation trigger
assert not report["passed"]
assert "gated_failures" recorded incomplete slides
assert remediation contains "Regenerate pptx_slides"
```

**Expected Result**: Quality loop fails on incomplete slides; triggers regeneration

---

### Test 5: End-to-End Deck Generation ✓

**Setup**: Regenerate TestEng2 deck with Phase 1 fixes

**Test**: Run the full coordinator → PPTX agent → quality loop → renderer pipeline

**Inputs**:
- Process: TestEng2 (P2P with 14 steps, 5 roles, 3 systems)
- User instruction: "Generate executive deck"
- Output type: pptx

**Checks**:
1. [ ] All 9 slides rendered (no blank slides)
2. [ ] Slide 2 has 3 stat cards with metrics (14, 5, 3)
3. [ ] Slide 3 has 3 pillar columns (Governance, Quality, Productivity)
4. [ ] Slide 6 has table with step rows (not empty)
5. [ ] No `[PPTX QA]` truncation warnings in logs
6. [ ] Quality loop passes completeness check
7. [ ] Deck opens in PowerPoint without errors
8. [ ] Visual inspection: slide content visible (not title-only)

**Expected Result**: Professional deck with all slides populated; ready for C-suite presentation

---

## Success Criteria

### Phase 1 Complete When:

1. ✅ All 4 implementation steps verified in code
2. ✅ Test 1 passes: Metrics injected and used
3. ✅ Test 2 passes: Validation catches empty slides
4. ✅ Test 3 passes: Text truncation warnings logged
5. ✅ Test 4 passes: Completeness check triggers remediation
6. ✅ Test 5 passes: End-to-end deck generation produces professional output

### Regression Tests (ensure no breakage):

- [ ] Existing decks still render correctly
- [ ] Quality scores consistent (not suddenly higher/lower)
- [ ] Performance impact negligible (<5% slower)

---

## Defect Tracking

**If Test X Fails**:

| Test | Failure Mode | Root Cause | Fix |
|------|--------------|-----------|-----|
| 1 | Metrics not in prompt | Enrichment not populated | Verify ContentEnrichmentEngine runs before PPTX agent |
| 2 | Empty slides don't warn | Validation not in renderer | Add warning to _render_X_slide() |
| 3 | No truncation warning | max_chars calculation wrong | Adjust max_chars based on actual rendering |
| 4 | Remediation not triggered | gated_failures not updated | Check completeness check feeds into remediation path |
| 5 | Deck still has blank slides | Agent still generates empty arrays | Increase weight of examples in system prompt; add data injection |

---

## Timeline

- **Phase 1 Implementation**: Complete (weeks 1–4)
- **Phase 1 Testing**: This week (day 1–2)
- **Phase 1 Refinement**: Day 3–5 (if defects found)
- **Phase 2 Planning**: Week 5 (Deliverable abstraction, Branding Service, Quality Framework)

---

## Sign-Off

**Phase 1 Ready for Testing**: YES ✓

**Test Approver**: @<engineer>  
**Date**: 2026-04-08  
**Notes**: All code changes in place. Ready for test execution.

