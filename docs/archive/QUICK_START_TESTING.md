# Quick Start: Testing the Agentic Loop

**Status:** ✅ Phase 0 & 1 Integration Complete
**Commit:** aa408db
**Latest:** 2026-04-05

---

## TL;DR - Get Started in 5 Minutes

### 1. Enable the Feature
```bash
export COORDINATOR_AGENTIC_LOOP_ENABLED=true
```

### 2. Start Services (2 terminals)
```bash
# Terminal 1
cd backend
python -m uvicorn app.main:app --reload

# Terminal 2
cd ../frontend
npm run dev
```

### 3. Test in UI
- Open http://localhost:3000
- Click "New Run"
- Send: "Create a short process document"
- Watch the logs for: `"Coordinator using agentic event loop (Phase 0)"`

### 4. Verify
- ✅ Log shows agentic loop active
- ✅ State transitions visible in logs
- ✅ Task board updates in UI
- ✅ Document generated successfully

### 5. Disable (if needed)
```bash
unset COORDINATOR_AGENTIC_LOOP_ENABLED
# Restart backend - uses old path automatically
```

---

## What You're Testing

### The New Agentic Loop
```
Input: User instruction
  ↓
Setup Phase: Context, planning, skill selection
  ↓
State Machine Loop:
  ├─ Planning: Generate execution plan
  ├─ Task Assignment: Assign ready tasks
  ├─ Execution: Run workers
  ├─ Replanning: If failures occur
  └─ Finalization: QA, guardrails, hooks
  ↓
Output: Generated documents
```

### vs. Old Linear Execution
```
Input: User instruction
  ↓
Setup Phase
  ↓
Parallel Fanout (3 workers at once)
  ↓
Finalization: QA, guardrails
  ↓
Output: Generated documents
```

---

## What to Look For in Logs

### Good Signs ✅
```
[INFO] Coordinator using agentic event loop (Phase 0)
[DEBUG] Coordinator state: init -> planning
[DEBUG] Coordinator state: planning -> task_assignment
[DEBUG] Coordinator state: task_assignment -> execution
[DEBUG] Coordinator state: execution -> task_assignment (more tasks)
[DEBUG] Coordinator state: execution -> finalize (done)
[DEBUG] Coordinator state: finalize -> done
[INFO] Setup phase complete: 7 tasks created
[INFO] Task task_1 completed
[INFO] Task task_2 completed
... (more task completions)
[INFO] Finalization phase complete
[INFO] Coordinator event loop completed
```

### Red Flags ❌
```
❌ TypeError: CoordinatorStateManager has no method...
❌ AttributeError: settings has no attribute...
❌ Coordinator state error: Invalid transition...
❌ Task execution failed with error
❌ max_replans exceeded
```

---

## Expected Output

### In the UI
- Run Studio opens with instruction box
- SwarmPanel shows task board
- Tasks appear with status:
  - queued → assigned → running → completed
- Status updates visible in real-time (< 2 seconds)
- Final outputs generated (docx, xlsx, etc.)

### In the Logs
- Clear state machine progression
- Task creation and completion
- No error messages
- Final "Coordinator event loop completed" message

### Total Time
- First run: ~45-60 seconds (includes planning)
- Setup phase: ~20-30 seconds
- Execution phase: ~20-30 seconds
- Finalization: ~5-10 seconds

---

## Troubleshooting

### "Coordinator using agentic event loop" not in logs
**Problem:** Flag not set or not recognized
**Solution:**
```bash
export COORDINATOR_AGENTIC_LOOP_ENABLED=true
echo $COORDINATOR_AGENTIC_LOOP_ENABLED  # Should print "true"
```

### Python module not found errors
**Problem:** Dependencies not installed
**Solution:**
```bash
# In backend directory
pip install -r requirements.txt
# Or
pip install pydantic sqlalchemy anthropic
```

### State transition errors
**Problem:** Invalid state machine transition
**Solution:**
1. Check logs for the error message
2. This indicates a bug in the state machine
3. Run with flag disabled to verify old path works
4. Report with error message + reproduction steps

### Tasks not completing
**Problem:** Task stuck in "running" state
**Solution:**
1. Check if worker process is hung
2. Look for timeout messages in logs
3. Increase `subagent_tool_max_rounds` if needed
4. Check if output directory has write permissions

---

## Testing Checklist

Run through this to verify everything works:

- [ ] Environment variable set (`COORDINATOR_AGENTIC_LOOP_ENABLED=true`)
- [ ] Backend starts without errors
- [ ] Frontend loads without errors
- [ ] Can create a new run
- [ ] Can submit an instruction
- [ ] Log shows "agentic event loop (Phase 0)"
- [ ] State transitions visible in logs
- [ ] Task board visible in UI
- [ ] Tasks progress through states (queued → completed)
- [ ] Document generated successfully
- [ ] No errors in console or logs
- [ ] QA/guardrails pass
- [ ] Output has expected format

**If all checked:** ✅ Phase 0 is working!

---

## Comparison Test

Want to compare old vs new paths?

### Test Old Path
```bash
# Default (no environment variable)
unset COORDINATOR_AGENTIC_LOOP_ENABLED
# Restart backend

# In logs, you'll see different execution pattern
# (parallel fanout instead of state machine)
```

### Test New Path
```bash
export COORDINATOR_AGENTIC_LOOP_ENABLED=true
# Restart backend

# In logs, you'll see state machine transitions
```

### Metrics to Compare
- Execution time (should be similar or better)
- Memory usage (should be similar)
- Output quality (should be identical)
- Task visibility (new path shows more detail)

---

## File Locations

For reference:

### Configuration
- `backend/app/core/config.py` - Config flags (lines 137-141)

### Core Implementation
- `backend/app/agents/coordinator.py` - run() method wiring (lines 1523-1530)
- `backend/app/agents/coordinator_state_manager.py` - State machine (full file)

### Documentation
- `PHASE_0_INTEGRATION_COMPLETE.md` - Detailed testing guide
- `IMPLEMENTATION_STATUS.md` - Complete implementation report
- `QUICK_START_TESTING.md` - This file

---

## FAQ

**Q: Will this break my existing runs?**
A: No! It's opt-in. Default behavior unchanged unless you set the env var.

**Q: How do I disable it?**
A: `unset COORDINATOR_AGENTIC_LOOP_ENABLED` then restart backend.

**Q: Is it safe to enable in production?**
A: Test first! It's opt-in so you can try on a replica environment.

**Q: What if something breaks?**
A: Disable the flag and restart. Old path automatically used.

**Q: When will this be the default?**
A: After successful testing and validation in multiple environments.

**Q: What's different from the old system?**
A: Task board drives execution instead of fixed linear order. Same outputs, better architecture.

**Q: Can I use both paths at the same time?**
A: Not per-run, but you can toggle between them by setting/unsetting the env var.

**Q: Is performance better?**
A: Should be similar or better. Task board overhead is minimal.

**Q: When is Phase 2 ready?**
A: Phase 2 (subprocess workers) is scaffolded but needs ~2 more weeks after Phase 0 validation.

---

## What's Next

### Immediate
1. Enable the flag and run tests
2. Verify output quality matches old path
3. Monitor logs for any issues
4. Try multiple runs with different instructions

### If Issues Found
- Disable flag
- Check if issue reproduces on old path
- Report with logs and reproduction steps

### If All Good
- Enable on staging environment
- Collect metrics (latency, memory, quality)
- Compare against old path
- Plan rollout to production

---

## Summary

✅ The agentic loop is ready
✅ Integration is complete
✅ Backward compatibility maintained
✅ Testing is straightforward

**Next action:** Set the environment variable and test!

For detailed information, see:
- `PHASE_0_INTEGRATION_COMPLETE.md` - Testing details
- `IMPLEMENTATION_STATUS.md` - Full technical report
