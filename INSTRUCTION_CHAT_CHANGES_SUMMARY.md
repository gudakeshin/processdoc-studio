# Instruction Chat Changes - Quick Reference

## Problem Diagnosed
The Run Studio instruction chat was displaying "guided decisions" prompts (deliverable type, output formats, strategy selection), which is the **older centralized format** that conflicts with the Cowork agent-driven model.

## Solution Implemented
**Hide decision prompts in Run Studio** while keeping them in Projects (for backwards compatibility).

---

## Files Changed

### 1. `frontend/components/run-studio/ZoneAInstruction.tsx`

**Added:** New optional prop `showGuidedDecisions`

```typescript
// Line 176 (added to params)
showGuidedDecisions = true,

// Line 195 (added to type definition)
showGuidedDecisions?: boolean;

// Line 324 (modified condition)
// OLD: {decisionPrompts.length > 0 ? (
// NEW: {showGuidedDecisions && decisionPrompts.length > 0 ? (
```

**Effect:** Component can now optionally hide decision prompts section

---

### 2. `frontend/components/run-studio/RunStudioView.tsx`

**Changed:** Pass `showGuidedDecisions={false}` when rendering ZoneAInstruction

```typescript
// Line 143 (added prop)
showGuidedDecisions={false}
```

**Effect:** Run Studio now doesn't show decision prompts to users

---

## Verification

### Before
```
User: "Create a process document"
↓
System: "What type of deliverable? proposal | report | SOP | deck"
System: "Which formats? docx | pptx | xlsx | pdf"
System: "Which strategy? default | custom"
↓
User: Selects options
↓
Run executes
```

### After
```
User: "Create a process document"
↓
System: Acknowledges instruction
↓
Run executes
(no intermediate decision prompts)
```

---

## What's NOT Broken

✅ Projects conversation still works (decision prompts visible there)
✅ Existing runs still function
✅ No backend changes needed
✅ Backwards compatible

---

## How to Test

1. Start backend and frontend
2. Open a run in Run Studio
3. Send an instruction: "Create an SOP"
4. ✅ Verify: No decision prompts appear
5. ✅ Verify: Run executes normally
6. (Optional) Open a project conversation - decision prompts should still appear there

---

## Why This Change

**Cowork Pattern:** Agents receive shared instruction → self-coordinate via message queue
**Old Pattern:** Centralized system asks humans for decisions → execute with decisions

This change removes the "ask for decisions" UI from runs, preparing the system for true Cowork coordination where:
- Instruction is broadcasted to all teammates
- Each teammate understands the goal directly
- No intermediate UI decisions needed
- Teams coordinate via message queue, not UI selections

---

## What Comes Next (Phase 2+)

Currently the instruction still uses "context injection" (passed in AgentContext). Future phases will:
1. Broadcast instruction via message queue when run starts
2. Create task-specific directives from instruction
3. Route directives to teammates per task assignment
4. Instruction becomes immutable once run starts

This provides full Cowork alignment where instruction flows through the coordination system, not through UI selections.

---

## Code Summary

**Total lines changed:** ~3
**Risk level:** Very low (purely UI, no logic changes)
**Backwards compatible:** Yes
**Testing needed:** Visual verification + existing tests should pass
