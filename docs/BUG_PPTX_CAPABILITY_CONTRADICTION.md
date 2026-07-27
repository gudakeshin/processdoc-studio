# Bug Analysis: PPTX Agent Capability Contradiction

**Date:** 2026-04-29  
**Status:** Fixed  
**Severity:** Medium (UX/Communication Issue)

## Problem Statement

The PPTX agent was making contradictory claims about its capabilities:

1. **Initial claim:** "I'm drafting the complete 8-slide PPTX with full speaker notes... ready for review shortly"
2. **When pressed for details:** "I can't generate the actual PPTX file itself... I can only deliver the narrative blueprint"

Users experienced broken expectations: promised PPTX delivery, then told the agent couldn't deliver it.

## Root Cause

The issue was **misleading language in system prompts and skill definitions** that confused the agent about what it produces.

### The Confusion Chain

1. **SKILL.md (pptx_v1) Line 43-47** said:
   ```
   This skill generates a JSON slide blueprint that is rendered 
   into a fully-branded PPTX deck by the platform renderer.
   ```
   
   This taught the agent: "I produce a **blueprint**; the **renderer** produces the PPTX"

2. **subagents.py Line 2560** said:
   ```
   You are producing a slide blueprint for python-pptx rendering.
   ```
   
   Again: "I make blueprints; someone else renders them"

3. **Logical conclusion** (from the agent's perspective):
   - ✅ "I produce JSON specs" (correct)
   - ✅ "The renderer converts those to PPTX" (correct)
   - ❌ "Therefore, I don't produce PPTX files" (WRONG — the specs ARE the PPTX)

### What the Agent Should Understand

The JSON output the agent produces IS the PPTX content, just in a structured intermediate format. The rendering is an **internal implementation detail**, not a separate deliverable step. From the user's perspective, the agent produces the PPTX file.

## The Fix

### 1. Updated SKILL.md (backend/config/skills/pptx_v1/SKILL.md)

**Before:**
```
This skill generates a JSON slide blueprint — ... rendered into a 
fully-branded python-pptx deck by the platform renderer.
```

**After:**
```
This skill generates the content specifications for a **fully-branded, 
production-ready PPTX presentation deck**. Your output is a structured 
`{"slides": [...]}` JSON object that the platform immediately renders 
into an actual .pptx file that users can download and open in 
PowerPoint. Your output IS the deck — no further manual steps needed.
```

**Key changes:**
- Emphasize that output is "production-ready" and "fully-branded"
- Clarify that the JSON **IS** the deck (not a blueprint for someone else to render)
- Explain that rendering is automatic with no manual steps needed

### 2. Updated subagents.py (backend/app/agents/subagents.py Line 2560)

**Before:**
```
You are a Deloitte presentation strategist producing a slide blueprint 
for python-pptx rendering.
```

**After:**
```
You are generating a production-ready PowerPoint presentation deck. 
Your JSON output will be immediately rendered into a fully-branded 
.pptx file that users can download and open.
```

**Key changes:**
- "Generating a deck" not "producing a blueprint"
- Explicitly state the output becomes a downloadable, usable .pptx file
- Emphasize immediacy ("immediately rendered")

## Verification

The system **already has the capability** to produce PPTX files end-to-end:

1. **Agent** (subagents.py `run_pptx_agent()`) → produces JSON slide specs
2. **Deliverable** (core/deliverable_pptx.py `PPTXDeliverable.render()`) → renders JSON to actual .pptx
3. **Output** → `output.pptx` file users can download and open

The pipeline is complete. The agent just needed to understand that its JSON output IS the deliverable.

## Testing

To verify the fix works:

1. Run a PPTX generation request in the ProcessDoc app
2. Observe that the agent (and any coordinating instances) correctly state it will deliver a working PPTX file
3. Verify the end result is an actual, usable .pptx file

## Impact

- **User experience:** Clear, consistent messaging about PPTX delivery
- **Agent behavior:** PPTX agent will correctly describe its capabilities
- **No API changes:** This is purely a clarification in prompt/instruction text
- **Backward compatible:** All existing PPTX functionality remains unchanged

## Lessons Learned

When an intermediate representation (JSON) is the input to an internal rendering service, be clear to agents that:
- The agent produces the **final deliverable** (just in intermediate form)
- The rendering is an implementation detail, not a separate process
- From the user's perspective, the agent's output IS the file they'll receive

Avoid terminology like "blueprint," "spec," or "for rendering by X" when the agent is actually producing the final deliverable. Use language that makes clear: "Your output is the X file that users will receive."
