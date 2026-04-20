# Debugging: Agentic Loop Not Activating

## Quick Diagnostic Steps

### Step 1: Run the Settings Test

```bash
cd /Users/pallavchaturvedi/Agentic\ Projects/Process\ Doc\ v2
python3 test_agentic_loop_settings.py
```

**Expected output:**
```
✅ RESULT: AGENTIC LOOP WOULD BE ENABLED
```

**If you see:**
```
❌ RESULT: AGENTIC LOOP WOULD BE DISABLED (old path)
```

Then we have a configuration issue to debug further.

---

### Step 2: Kill All Running Processes

```bash
pkill -f "uvicorn app.main:app"
pkill -f "npm run dev"
pkill -f "node"
sleep 2
```

---

### Step 3: Restart Backend with Full Logging

```bash
cd /Users/pallavchaturvedi/Agentic\ Projects/Process\ Doc\ v2/backend
python -m uvicorn app.main:app --reload --log-level warning
```

**Watch for these messages immediately (within first few seconds):**
```
🎯🎯🎯 AGENTIC LOOP ENABLED - USING NEW STATE MACHINE PATH 🎯🎯🎯
```

OR

```
⚠️⚠️⚠️ AGENTIC LOOP DISABLED - USING OLD THREADPOOL PATH ⚠️⚠️⚠️
```

---

### Step 4: Start Frontend (in new terminal)

```bash
cd /Users/pallavchaturvedi/Agentic\ Projects/Process\ Doc\ v2/frontend
npm run dev
```

---

### Step 5: Create a Test Run

1. Open http://localhost:3000
2. Click "New Run"
3. Type instruction: "Create a short document"
4. Click Start

---

### Step 6: Check Backend Logs

Watch the backend terminal for these debug messages:

```
✓ Successfully read setting directly: coordinator_agentic_loop_enabled = True
DEBUG: Type of agentic_loop_enabled = <class 'bool'>
DEBUG: Boolean value = True
DEBUG: All settings attributes with 'coordinator': [...]
🎯🎯🎯 AGENTIC LOOP ENABLED - USING NEW STATE MACHINE PATH 🎯🎯🎯
```

Then you should see state transitions:
```
[DEBUG] Coordinator state: init -> planning
[DEBUG] Coordinator state: planning -> task_assignment
[DEBUG] Setup phase complete: 7 tasks created
[DEBUG] Coordinator state: task_assignment -> execution
```

---

## What to Do With Results

### If you see "AGENTIC LOOP ENABLED" messages:
✅ **Success!** The agentic loop is working. You should see state transitions in the logs and the task board should be visible in the UI.

### If you see "AGENTIC LOOP DISABLED" messages:
❌ **Configuration issue**. The setting is not being read as `True`.

**Next step:** Copy the output from `test_agentic_loop_settings.py` and share it so we can diagnose why the setting isn't being read.

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'dotenv'"

The Python environment doesn't have dependencies installed. This is OK - the actual backend server will have them. Just skip the diagnostic script and go straight to restarting the backend in Step 3.

### "File exists" git error

This is a git lock issue, not related to the agentic loop. Run:
```bash
rm -f .git/index.lock
```

Then proceed.

### Still seeing old workflow after restart

Make sure you:
1. ✓ Killed all running processes (Step 2)
2. ✓ Restarted backend from the correct directory (Step 3)
3. ✓ Waited a few seconds for backend to fully start
4. ✓ Created a NEW run after restart (old browser tabs may use old code)

Try hard-refreshing the frontend:
```
Chrome/Safari: Cmd+Shift+R
Firefox: Ctrl+Shift+R
```

---

## Debug Log Locations

The agentic loop debug logs appear **when the Coordinator.run() method is called**, which happens when you submit a run instruction.

**To see them:**
1. Look at the backend terminal
2. Create a new run
3. Check the logs immediately after clicking "Start"

The DEBUG messages should appear within 1-2 seconds of starting the run.

---

## Next Steps

1. Run the diagnostic script
2. Restart backend and frontend
3. Create a test run
4. Check for the debug messages
5. Share the results if the agentic loop isn't activating

I'll be able to fix it once I see what's actually happening!
