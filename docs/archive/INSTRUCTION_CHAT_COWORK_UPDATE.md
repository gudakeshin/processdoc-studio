# Instruction Chat Cowork Alignment Update

**Date:** 2026-04-04
**Status:** ✅ Phase 1 (UI Simplification) Complete
**Scope:** Align Run Studio instruction chat with Claude Cowork pattern

---

## What Changed

### ✅ Completed: Phase 1 - UI Simplification

**Objective:** Remove "guided decisions" UI from Run Studio to align with Cowork's agent-driven model

**Changes Made:**

#### 1. **Frontend: ZoneAInstruction Component**
- **File:** `frontend/components/run-studio/ZoneAInstruction.tsx`
- **Change:** Added `showGuidedDecisions?: boolean = true` prop
- **Effect:** When `false`, decision prompts section is not rendered

#### 2. **Frontend: RunStudioView Integration**
- **File:** `frontend/components/run-studio/RunStudioView.tsx`
- **Change:** Pass `showGuidedDecisions={false}` to ZoneAInstruction
- **Effect:** Decision prompts now hidden in Run Studio (only shown in Projects)

#### 3. **Backend: Decision Prompts Generation**
- **File:** `backend/app/api/projects.py`
- **Status:** Unchanged (still generates decision_prompts)
- **Rationale:** Backend can generate them, frontend just doesn't display them for runs

---

## Before vs After

### OLD FORMAT (Before)
```
User sends instruction
    ↓
System shows decision prompts (deliverable type, outputs, strategy)
    ↓
User selects options via dropdown UI
    ↓
Decisions merged into instruction
    ↓
Run executes with selected decisions
```

**Problem:** Guided, human-heavy, centralized workflow

### NEW FORMAT (After, Phase 1)
```
User sends instruction
    ↓
Instruction stored in run context
    ↓
No decision prompts shown
    ↓
Run executes with full instruction
    ↓
(Future: Instructions distributed via message queue to teammates)
```

**Benefit:** Simplified, agent-centric, prepares for Cowork integration

---

## Impact

| Aspect | Before | After |
|--------|--------|-------|
| **Run Studio UI** | Shows decision prompts with dropdown selection | Clean instruction input only |
| **User Experience** | Guided workflow, human makes decisions | Direct instruction, agent-driven |
| **Compatibility** | Projects still work as before | Projects unchanged (still have decision prompts) |
| **Cowork Alignment** | Not aligned | Partially aligned (UI level) |

---

## What This Enables

✅ **Immediate:**
- Cleaner, simpler Run Studio interface
- No decision prompt friction in user workflow
- Instruction becomes primary input source

🔄 **Future (Phase 2+):**
- Instruction broadcast via message queue to all teammates
- Task-specific directives extracted from instruction
- Teammates read instruction once, coordinate via queue
- True agent-driven execution without UI guidance

---

## Testing

To verify the changes work:

1. **Start the backend and frontend**
2. **Create a new run in Run Studio**
3. **Send an instruction message**
4. ✅ **Verify:** No "Guided decisions" section appears
5. ✅ **Verify:** Projects conversation still shows decision prompts (if accessed separately)

```bash
# Run tests
pytest backend/app/tests/test_auth_hitl.py -v  # Tests still pass
npm run test -- ZoneAInstruction                 # Component tests
```

---

## What's NOT Changed Yet

❌ **Backend decision prompt generation** still runs for conversations
- Reason: Projects still use it; minimal performance impact
- Can optimize later if needed

✅ **Instruction → swarm message queue (when swarm is on)** — On `POST /api/runs`, the run instruction is persisted as a **broadcast** `SwarmMessage` and a `swarm_message` run event (see `persist_instruction_broadcast_swarm_event_payload` in `backend/app/services/swarm.py`). Disabled when `SWARM_ORCHESTRATION_ENABLED` is false.

❌ **Task-specific directives** (Phase 3 — deferred)
- Not implemented in this pass
- Requires coordinator / LLM or heuristics to split free text, then `send_message(..., to_teammate=...)` with idempotency
- **Follow-up checklist:** (1) define directive schema (per-teammate bullet list vs structured JSON), (2) prompt + tool or post-plan hook, (3) avoid duplicate DMs on retry, (4) surface in Swarm panel / run artifacts

---

## Files Modified

```
frontend/components/run-studio/ZoneAInstruction.tsx   (showGuidedDecisions + instructionChatCowork gate)
frontend/components/run-studio/RunStudioView.tsx        (showGuidedDecisions={false})
frontend/lib/instructionChatCowork.ts                   (testable gate)
frontend/lib/instructionChatCowork.test.ts
frontend/components/run-studio/SwarmPanel.tsx         (comment: SSE refetch for swarm_message)
backend/app/services/swarm.py                         (persist_instruction_broadcast_swarm_event_payload)
backend/app/api/runs.py                               (start_run: append swarm broadcast when enabled)
backend/app/tests/test_swarm_http.py                  (broadcast on / off)
```

---

## Cowork Alignment Progress

| Phase | Component | Status |
|-------|-----------|--------|
| Phase 0.5 | Instruction Chat UI | ✅ **DONE** |
| Phase 0 | Coordinator Event Loop | 🔄 In Progress (from earlier context) |
| Phase 1 | Task Scheduler | 🔄 In Progress (from earlier context) |
| Phase 2 (instruction broadcast) | Swarm mailbox on run create | ✅ **DONE** (flag-gated) |
| Phase 3 | Task-specific directives / peer DMs | 📋 Deferred (see above) |
| Phase 4 | Git Worktrees | 📋 Planned |

---

## Next Steps

### Immediate (If needed)
- ✅ Test the UI changes end-to-end
- ✅ Verify Projects still work correctly
- Optional: Remove unused `onSubmitDecisions` callbacks from RunStudioView if not needed

### Phase 2+ (From existing plan)
- [x] Broadcast instruction via message queue on run creation (`SWARM_ORCHESTRATION_ENABLED=true`)
- [x] Teammates / UI see broadcast via existing `GET .../swarm/messages` and `SwarmPanel` refetch (`liveEventsLength` + poll)
- [ ] Extract task-specific directives from instruction (Phase 3)
- [ ] Route directives to teammates via `send_message()` (Phase 3)
- [ ] Preserve instruction history in run artifacts (optional enhancement)

---

## Architecture Implications

**Before:** Instruction → UI Decisions → Agent Execution
- Central point: UI decision selection
- Pattern: Human-in-the-loop, guided workflow

**After:** Instruction → Agent Execution → Message Queue Coordination
- Central point: Message queue broadcast
- Pattern: Agent-driven, self-organized teams

This change shifts from "coordinator asks human" to "teammates read shared instruction and coordinate". It's the first step toward true Cowork alignment.

---

## Backwards Compatibility

✅ **Backwards compatible**
- Projects feature unchanged
- Existing runs still work
- Run Studio UI hides guided decisions as before
- `POST /api/runs` response shape unchanged; when swarm is enabled, an extra `SwarmMessage` row and `swarm_message` event are added (no breaking API change)

---

## Summary

The Run Studio instruction chat has been simplified to remove guided decision prompts, aligning it with the Cowork pattern. This is Phase 0.5 of the broader Cowork alignment effort.

**Current State:** ✅ Ready for testing
**Next Phase:** Phase 3 — task-specific directives and targeted teammate messaging (see deferred checklist above).

**Optional polish (Option A):** `useRunStudio` still resolves `decision_prompts` metadata when hidden in Run Studio; harmless. Option B would skip that work when `showGuidedDecisions={false}`.
