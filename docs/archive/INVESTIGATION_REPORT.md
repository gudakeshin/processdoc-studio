# Investigation Report: Proposal Generation & QA Loop Failures

## Executive Summary

The proposal generated (`MyEngagement_Processnarrative_20260405.docx`) is a **deterministic fallback template** filled with [TBC] placeholders, indicating:

1. **Primary Issue**: Claude generation is not being called or is failing, causing the workflow to fall back to a hardcoded template
2. **Secondary Issue**: The QA loop is not catching this low-quality output and triggering remediation
3. **Root Cause**: Likely a combination of Claude generation failure + QA loop evaluation gaps

---

## Issue Analysis

### Generated Content vs. Expected Content

**Generated Proposal** (from MyEngagement_Processnarrative_20260405.docx):
- Exactly matches `_docx_deterministic_fallback()` template in `subagents.py` lines 1669-1699
- Structure:
  - `# Finance Transformation Proposal — {name}`
  - `## Executive Summary`
  - `## Current State and Problem Statement`
  - `## Target Operating Model`
  - `## Workstreams and Timeline`
  - `## Value Case` with `| Close acceleration | [TBC] | Medium | CFO office |`
  - `## Risks and Mitigations`
  - `## Next Steps`

**Expected (Claude-Generated) Proposal**:
- Customized sections from quality contract `proposal_finance_v1.json`
- Client-specific content from `assembled_context` + `ProcessModel`
- Multiple citations/evidence markers
- Quantified value case with client-specific metrics
- Custom risk assessment

### Why the Fallback Template Was Used

**Execution Flow in `run_docx_agent()` (lines 1471-1613)**:

```
1. Check is_claude_enabled() — should return True (API key is set in .env)
2. Call _run_subagent_tool_loop_text() → returns None/empty
3. Call claude_generate() → returns None/empty OR throws exception
4. Check if md is str and stripped → fails
5. Return _docx_deterministic_fallback() template
```

**Verdict**: Claude generation is not executing successfully, causing immediate fallback to template.

---

## Root Cause Analysis

### Issue #1: Claude Generation Failure

**Location**: `backend/app/agents/subagents.py`, lines 1600-1606

```python
md = _run_subagent_tool_loop_text(ctx, agent_id="docx", system=sb.system, user=user,
                                  temperature=sb.temperature, max_rounds=sb.max_rounds)
if not md:
    try:
        md = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=2200)
    except Exception:
        md = None
```

**Possible causes**:
1. `is_claude_enabled()` returns False (checked: API key IS set in `backend/.env`)
2. `_run_subagent_tool_loop_text()` is consuming the generation and returning None
3. `claude_generate()` is throwing an exception that's silently caught
4. Network/API timeout or circuit breaker is active
5. Token limit exceeded during generation

**Evidence**:
- API key is set: `ANTHROPIC_API_KEY=sk-ant-api03-...` in `backend/.env` (line 3)
- `is_claude_enabled()` checks: `bool(getattr(settings, "anthropic_api_key", ""))` — should pass
- No logging visible for the exception being caught

### Issue #2: QA Loop Not Catching Template Output

**Location**: `backend/app/agents/coordinator.py`, lines 2108-2115

```python
dq_report, outputs = run_deliverable_quality_loop(
    state=state,
    wanted=wanted,
    outputs=outputs,
    apply_remediation=self._apply_qa_remediation,
    emit_event=emit_event,
    project_id=str(project_id) if project_id else None,
)
```

**Expected QA Evaluation**:
- **Section Coverage** (38% weight): Check for required sections
  - Contract requires: "Executive Summary", "Current State and Problem Statement", "Solution on a Page", etc.
  - Generated has: Similar names but slightly different structure
  - Regex check at line 67 of `deliverable_quality.py`: `re.search(rf"^#+\s*{escaped}\s*$", norm, flags=re.MULTILINE)`
  - **Problem**: Regex looks for markdown headers like `## Executive Summary`, but template has `## Executive Summary` as a line, not necessarily as a standalone header match

- **Citation Density** (22% weight): Check for evidence markers
  - Required: Minimum 2 citation markers (`[123]`, `(source:...)`, URLs)
  - Generated: ZERO citations (fails with score 0.0/2.0)
  - **This should fail the dimension!**

- **LLM Critique** (40% weight): Evaluate content quality
  - Rubric: "Problem-led opening, concrete workstreams and ownership, measurable value case with assumptions, explicit risks/mitigations, no duplicate filler"
  - Generated: Generic template language with [TBC] placeholders everywhere
  - **This should score poorly!**

**Expected aggregate score**:
```
structure:    0.7 × 0.38 = 0.266  (some sections match, but names differ)
evidence:     0.0 × 0.22 = 0.000  (zero citations)
rubric_fit:   0.3 × 0.40 = 0.120  (generic template language, [TBC] placeholders)
────────────────────────────────
aggregate:            0.386  (FAILS threshold of 0.82)
```

**Why it's not catching the failure**:
1. `deliverable_quality_enabled` defaults to True (no override in config)
2. Quality contract IS being loaded: `proposal_finance_v1.json` exists with proper config
3. **POSSIBLE**: Section regex is not matching correctly due to section name differences
4. **POSSIBLE**: Citation density evaluation is being skipped or not counted
5. **POSSIBLE**: `is_claude_enabled()` is False, so LLM critique falls back to 0.78 (line 99 of `deliverable_quality.py`)
6. **POSSIBLE**: QA results are not being checked before returning the output

---

## Specific Code Issues

### 1. Missing Error Handling in Claude Generation (Subagents)

**File**: `backend/app/agents/subagents.py`, lines 1600-1606

**Issue**: Exception from `claude_generate()` is silently caught. No logging or telemetry of the failure.

**Impact**: Users don't know Claude generation failed; they get the template without warning.

**Fix**: Add logging and potentially raise an error or set a flag indicating generation failure.

### 2. Section Name Mismatch in Quality Contract

**File**: `backend/config/quality_contracts/proposal_finance_v1.json`, line 33

**Issue**: Contract requires section "Solution on a Page" but deterministic fallback doesn't include this section.

**Impact**: Section coverage check might not correctly identify missing sections.

**Expected sections**:
```json
[
  "Executive Summary",
  "Current State and Problem Statement",
  "Solution on a Page",  ← MISSING in fallback
  "Workstreams and Timeline",
  "Value Case",
  "Risks and Mitigations",
  "Governance and Team Structure",  ← MISSING in fallback (replaced with "Next Steps")
  "Next Steps"
]
```

**Generated sections**:
```
1. Executive Summary
2. Current State and Problem Statement
3. Target Operating Model  ← DIFFERENT NAME
4. Workstreams and Timeline
5. Value Case
6. Risks and Mitigations
7. Next Steps  ← MISSING "Governance and Team Structure"
```

### 3. Regex Section Matching Issue

**File**: `backend/app/services/deliverable_quality.py`, lines 67-70

```python
if re.search(rf"^#+\s*{escaped}\s*$", norm, flags=re.MULTILINE):
    continue
if label.lower() in norm:
    continue
missing.append(label)
```

**Issue**: Regex requires exact header match with markdown formatting. If the text has extra content after the header, it won't match.

**Example**:
- Looking for: "Solution on a Page" (with markdown ## prefix)
- Found in text: (not found at all)
- Fallback: Checks if "solution on a page" appears anywhere in the document — it doesn't

### 4. Citation Density Not Strict Enough

**File**: `backend/app/services/deliverable_quality.py`, lines 79-91

**Issue**: Citation patterns check for `[digits]`, `(source:...)`, or URLs. Zero citations should be a hard failure.

**Current logic**:
```python
count = 0  # Zero citations found
min_m = 2  # Minimum required
score = min(1.0, float(count) / float(max(1, min_m)))
score = min(1.0, 0.0 / 2) = 0.0
```

**Weight**: 22%
**Score**: 0.0
**Weighted contribution**: 0.0 × 0.22 = 0.0

**Problem**: This should be a red flag, but if the other dimensions score high enough, it can be masked.

### 5. LLM Critique Fallback When Claude Disabled

**File**: `backend/app/services/deliverable_quality.py`, line 98-99

```python
if not is_claude_enabled() or len(text.strip()) < 80:
    return 0.78, {"fallback": True, "note": "claude_disabled_or_short"}
```

**Issue**: If Claude is disabled, LLM critique returns 0.78 as a fallback score.

**Impact**:
- If Claude generation failed (because Claude is disabled), the fallback is used
- QA loop runs, but the LLM critique (40% weight) returns fallback 0.78 instead of actually evaluating
- **This masks low-quality output!**

**Calculation with fallback**:
```
structure:    0.7 × 0.38 = 0.266
evidence:     0.0 × 0.22 = 0.000
rubric_fit:   0.78 × 0.40 = 0.312  ← FALLBACK VALUE!
────────────────────────────────
aggregate:            0.578  (still below 0.82, but closer than 0.386)
```

---

## Remediation Not Applied

**Why QA results aren't triggering remediation**:

1. QA loop evaluates and gets aggregate < 0.82
2. `_build_remediation()` generates action items (lines 165-204)
3. BUT: Need to check if `apply_remediation` callback is actually being invoked

**Location**: `backend/app/services/deliverable_quality.py`, line 311

```python
working = apply_remediation(state, wanted, gated_failures)
```

**Potential issue**: If remediation callback returns the same output (unchanged), the loop detects no progress and exits (line 307-309).

---

## Summary of Findings

| Issue | Severity | Root Cause | Impact |
|-------|----------|-----------|--------|
| Claude generation failing silently | **CRITICAL** | Unknown (likely network, timeout, or circuit breaker) | Proposal always falls back to template |
| Section name misalignment | **HIGH** | Contract specifies sections that fallback doesn't match | QA section coverage check may not detect missing sections |
| Citation density = 0 but weight only 22% | **MEDIUM** | No citations in template, but other dimensions might compensate | Low-quality output not flagged as critical failure |
| LLM critique fallback to 0.78 | **MEDIUM** | Claude disabled → LLM critique skipped → fallback score | Quality gate masks poor content when Claude generation fails |
| Missing error logging | **MEDIUM** | Silent exception catching | Users unaware of generation failure |
| Remediation callback not invoked | **MEDIUM** | QA loop might be returning early or failing | Failed outputs never get remediated |

---

## Recommendations

### Immediate Fixes

1. **Debug Claude Generation Failure** (Priority 1)
   - Add logging to `claude_generate()` calls in `subagents.py`
   - Check circuit breaker status and API rate limits
   - Verify API key is being loaded correctly
   - Add telemetry for generation failures

2. **Align Quality Contract with Fallback** (Priority 1)
   - Update contract to match fallback template section names, OR
   - Update fallback template to match contract section names
   - Add "Solution on a Page" section to fallback or remove from contract

3. **Fix LLM Critique Fallback Logic** (Priority 2)
   - Don't return 0.78 when Claude is disabled
   - Instead, raise or skip the dimension entirely
   - Or: Make Claude enabled a hard requirement for proposal generation

4. **Add Hard Failure for Zero Citations** (Priority 2)
   - If citation_density < 0.5, don't allow other dimensions to compensate
   - OR: Increase citation_density weight to 0.5 (from 0.22)

5. **Improve QA Loop Logging** (Priority 3)
   - Log when QA loop is called
   - Log evaluation results for each dimension
   - Log remediation actions taken
   - Help diagnose why remediation wasn't applied

### Long-term Improvements

1. **Separate Skill-Level QA from Finalization-Phase QA**
   - In-process `_apply_quality_gate()` should catch obvious template outputs
   - Add check: if output matches deterministic fallback, fail the gate

2. **Add Deliverable Type Validation**
   - Ensure proposal deliverable only proceeds with Claude generation
   - Don't allow fallback for proposal (or mark it as degraded)

3. **Implement Circuit Breaker Observability**
   - Expose circuit breaker status in logs
   - Alert when circuit breaker is active

4. **Strengthen Template Detection**
   - Add metadata to fallback templates identifying them as such
   - Check for [TBC] markers as a sign of incomplete generation
   - Block delivery of [TBC]-filled proposals without user override

---

## Test Strategy

Once fixes are applied:

1. **Verify Claude is enabled**: Check logs show API key loaded
2. **Generate a proposal**: Ensure Claude is actually called (not fallback)
3. **Run QA loop**: Verify all dimensions are evaluated correctly
4. **Check remediation**: If QA fails, verify remediation is applied
5. **Validate output**: Ensure final proposal has citations and client-specific content
6. **Check final score**: Aggregate should be > 0.92 (skill threshold) before returning

