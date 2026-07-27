# Process Doc Studio — Component Integration Guide

## Overview

This guide walks you through integrating the redesigned components (ApprovalBannerRedesigned, ActivityFeedRedesigned, SystemBanner) into RunStudioView. All components are drop-in replacements with no breaking changes to existing data flow.

**Estimated time**: 30–45 minutes  
**Complexity**: Medium (straightforward component swaps + minor layout adjustments)  
**Files to modify**: `RunStudioView.tsx`, `globals.css`

---

## Phase 1: Copy Files (5 minutes)

Verify all new files are in place:

```bash
# Components (should exist)
ls frontend/components/run-studio/ApprovalBannerRedesigned.tsx
ls frontend/components/run-studio/ActivityFeedRedesigned.tsx
ls frontend/components/run-studio/SystemBanner.tsx
ls frontend/components/run-studio/RunStudioLayout.tsx

# Styles (should exist)
ls frontend/styles/tokens-redesign.css
```

All files should exist from the creation phase. If any are missing, re-create them following the reference implementation.

---

## Phase 2: Update global styles (2 minutes)

Add the redesigned token stylesheet to your global styles.

**File**: `frontend/styles/globals.css`

**Action**: Add import after `tokens.css`

```diff
  @import "./tokens.css";
+ @import "./tokens-redesign.css";
  @import "./matrix-pane.css";
  @import "tailwindcss";
```

**Why**: The new tokens (--status-ok, --status-warn, --accent-primary, etc.) become available to all components without affecting existing styles.

---

## Phase 3: Update RunStudioView imports (2 minutes)

Add imports for the new components.

**File**: `frontend/components/run-studio/RunStudioView.tsx`

**Action**: Add these imports near the top (around line 90):

```diff
  import { ApprovalBanner } from "./ApprovalBanner";
+ import { ApprovalBannerRedesigned } from "./ApprovalBannerRedesigned";
  import { ToolActivityFeed } from "./ToolActivityFeed";
+ import { ActivityFeedRedesigned } from "./ActivityFeedRedesigned";
+ import { SystemBanner } from "./SystemBanner";
  import { Button } from "@/components/ui/Button";
```

---

## Phase 4: Integrate SystemBanner (5 minutes)

Add system banner alerts at the top of RunStudioView.

**File**: `frontend/components/run-studio/RunStudioView.tsx`

**Location**: In the main return JSX, add a sticky top bar above the grid layout.

**Before**:
```typescript
return (
  <div className="...">
    {/* Alert banner / status display section */}
    {expectedFlowGuidance && ...}
    
    <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      {/* content */}
    </div>
  </div>
);
```

**After**:
```typescript
return (
  <div className="...">
    {/* Top sticky bar with system banners */}
    <div className="sticky top-0 z-40 border-b border-[#E0E0E0] bg-white">
      {pollMode && (
        <SystemBanner
          type="info"
          title="Polling mode active"
          detail="Waiting for stream reconnection..."
        />
      )}
      {approvalBannerState?.type === "plan_blocked" && (
        <SystemBanner
          type="error"
          title="Governance checks failed"
          detail={approvalBannerState.blockedReason}
        />
      )}
      {streamError && (
        <SystemBanner
          type="warn"
          title="Stream error"
          detail={streamError}
        />
      )}
    </div>

    <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      {/* content */}
    </div>
  </div>
);
```

---

## Phase 5: Swap ApprovalBanner (1 minute)

Replace the old approval banner with the new one.

**File**: `frontend/components/run-studio/RunStudioView.tsx`

**Location**: Find the existing `<ApprovalBanner state={approvalBannerState} />` (around line 183)

**Before**:
```typescript
<ApprovalBanner state={approvalBannerState} />
```

**After**:
```typescript
<ApprovalBannerRedesigned state={approvalBannerState} />
```

No other changes needed — same prop interface.

---

## Phase 6: Swap ActivityFeed (5 minutes)

Replace ToolActivityFeed with the redesigned version.

**File**: `frontend/components/run-studio/RunStudioView.tsx`

**Location**: Find the `<ToolActivityFeed {...} />` call (around line 185–200)

**Before**:
```typescript
<ToolActivityFeed
  events={liveEvents}
  parsedEvents={parsedRunEvents}
  runChecklistTodos={runChecklistTodos}
  artifacts={artifacts}
  pollMode={pollMode}
  streamError={streamError}
  // ... other props
/>
```

**After**:
```typescript
<ActivityFeedRedesigned
  parsedEvents={parsedRunEvents}
  artifacts={artifacts.ready_downloads || []}
  runTodos={runChecklistTodos || []}
  contextMetadata={{
    leadingPractices: artifacts?.leading_practices || [],
    nonNegotiables: artifacts?.memory_summary?.non_negotiables || [],
  }}
  permissionStages={/* See mapping section below */}
  width={360}
/>
```

### Prop Mapping Details

**parsedEvents** (required)
- Source: `parsedRunEvents` from hook
- Type: `ParsedRunEvent[]`
- Already structured; pass directly

**artifacts** (required)
- Source: `artifacts.ready_downloads` or similar
- Type: Array of artifact objects
- Filter to only "ready" artifacts if needed

**runTodos** (required)
- Source: `runChecklistTodos` from hook
- Type: `RunTodoRow[]`
- Pass as-is, may be empty array

**contextMetadata** (optional)
- Source: Extract from `artifacts` object
- Example:
  ```typescript
  contextMetadata={{
    leadingPractices: artifacts?.leading_practices?.slice(0, 4) || [],
    nonNegotiables: artifacts?.memory_summary?.non_negotiables || [],
  }}
  ```
- If not available, omit the prop (component handles undefined)

**permissionStages** (optional)
- Source: Permission/hook panel state
- Example:
  ```typescript
  permissionStages={
    permissionPanel?.result?.stages?.map((s: any) => ({
      name: s.name,
      status: s.approved ? "approved" : s.blocked ? "blocked" : "pending",
      timestamp: s.timestamp,
    })) || []
  }
  ```
- If governance info unavailable, omit the prop

**width** (optional)
- Default: 360px (standard sidebar width)
- Adjust if your sidebar is a different size

---

## Phase 7: Test locally (15 minutes)

Start dev server and verify integration.

### Setup

```bash
cd frontend
npm run dev
```

Navigate to a run page (e.g., `/projects/[pid]/runs/[rid]`).

### Checklist

- [ ] **Page loads** — No console errors, components render
- [ ] **ApprovalBannerRedesigned** — Appears when state is set; correct styling per state type
- [ ] **ActivityFeedRedesigned** — All tabs (Activity, Artifacts, Context, Governance) are clickable
- [ ] **SystemBanner** — Appears for poll mode, governance errors, stream errors
- [ ] **Chat works** — Messages send/receive normally
- [ ] **Approval flow** — Clicking approve/resimulate triggers correct action
- [ ] **Events display** — Activity tab shows running/completed skills
- [ ] **Responsive** — Sidebar visible on xl screen, hidden on smaller
- [ ] **Styling** — Colors match design tokens, no visual regressions

### Common Issues

**Issue**: Components don't appear or console shows errors

- **Fix**: Verify imports are added correctly. Check that component files exist at exact paths.
- **Check**: `npm run build` to catch TypeScript errors before testing.

**Issue**: SystemBanner appears but style is wrong

- **Fix**: Ensure `tokens-redesign.css` is imported in `globals.css`. Do a hard refresh (Cmd+Shift+R).
- **Check**: Inspect element to see if CSS variables are being applied.

**Issue**: ActivityFeed shows no events

- **Fix**: Verify `parsedRunEvents` is populated. Check that `buildSkillGroups()` receives valid events.
- **Check**: Open browser DevTools, check the props being passed to the component.

**Issue**: Approval button doesn't work

- **Fix**: Ensure `onApprove` / `onResimulate` callbacks are wired up from parent.
- **Check**: Verify that state is being updated after the async call completes.

---

## Phase 8: Optional - Add Theme Toggle (10 minutes)

If you want to let users customize density or accent color at runtime, use data attributes.

### Add state to RunStudioView

```typescript
const [density, setDensity] = useState<"comfortable" | "compact">("comfortable");
const [accentColor, setAccentColor] = useState<"green" | "blue" | "black" | "amber">("green");
```

### Apply to root element

```typescript
return (
  <div
    data-density={density}
    data-accent={accentColor}
    className="min-h-screen"
  >
    {/* content */}
  </div>
);
```

### Add toggle buttons (optional)

```typescript
<div className="fixed bottom-4 left-4 z-50 bg-white border rounded p-3">
  <select
    value={density}
    onChange={(e) => setDensity(e.target.value as any)}
  >
    <option value="comfortable">Comfortable</option>
    <option value="compact">Compact</option>
  </select>
  <select
    value={accentColor}
    onChange={(e) => setAccentColor(e.target.value as any)}
  >
    <option value="green">Green</option>
    <option value="blue">Blue</option>
    <option value="black">Black</option>
    <option value="amber">Amber</option>
  </select>
</div>
```

All styles automatically adapt via CSS custom properties in `tokens-redesign.css`.

---

## Reference: Component Props

### ApprovalBannerRedesigned

```typescript
<ApprovalBannerRedesigned
  state={{
    type: "hitl_gate" | "review_ready" | "plan_blocked" | null;
    reason?: string;                // For hitl_gate
    busy?: boolean;                 // For review_ready
    onApprove?: () => Promise<void>;
    onResimulate?: () => Promise<void>;
    blockedReason?: string;         // For plan_blocked
    blockedStage?: string;
    blockedCode?: string;
  }}
/>
```

### ActivityFeedRedesigned

```typescript
<ActivityFeedRedesigned
  parsedEvents={parsedRunEvents}
  artifacts={[
    { name: "deck.pptx", status: "ready", type: "PPTX", size: 5000 },
    // ...
  ]}
  runTodos={runChecklistTodos}
  contextMetadata={{
    leadingPractices: ["Practice 1", "Practice 2"],
    nonNegotiables: ["Requirement 1"],
  }}
  permissionStages={[
    { name: "PII Check", status: "approved", timestamp: "2 min ago" },
  ]}
  width={360}
/>
```

### SystemBanner

```typescript
<SystemBanner
  type="info" | "warn" | "error"
  title="Banner title"
  detail="Optional detail text"
  action={{
    label: "Action label",
    onClick: () => { /* ... */ }
  }}
  dismissible={true}
  onDismiss={() => { /* ... */ }}
/>
```

---

## CSS Custom Properties Reference

### Status Colors

```css
--status-ok: #2d7a3b;     /* Success */
--status-warn: #b8651a;   /* Warning */
--status-error: #b23c3c;  /* Error/blocked */
--status-info: #0072b1;   /* Info/running */
```

### Accent Variants

Applied via `[data-accent]` attribute:

```css
--accent-green: #2d7a3b;  /* Default */
--accent-blue: #0072b1;
--accent-black: #000000;
--accent-amber: #d4a574;
```

### Density Variants

Applied via `[data-density]` attribute:

```css
/* Comfortable (default) */
--density-comfortable-gap: 12px;
--density-comfortable-px: 16px;
--density-comfortable-py: 12px;

/* Compact */
--density-compact-gap: 8px;
--density-compact-px: 12px;
--density-compact-py: 8px;
```

---

## Troubleshooting

### Q: My styles aren't applying even after hard refresh

**A**: 
1. Check that `tokens-redesign.css` is imported in `globals.css`
2. Verify the file exists at `frontend/styles/tokens-redesign.css`
3. Do a full rebuild: `npm run build`
4. Clear `.next` folder: `rm -rf .next && npm run dev`

### Q: Activity feed shows no events even though run is executing

**A**:
1. Open browser DevTools → Elements
2. Inspect the `<ActivityFeedRedesigned>` component
3. Check the props being passed — specifically `parsedEvents`
4. Verify `parsedRunEvents` is being populated in the parent hook
5. Check browser console for any React warnings about invalid prop types

### Q: Approval banner is always disabled/busy

**A**:
1. Verify the state object structure matches `ApprovalBannerState`
2. Check that `onApprove` / `onResimulate` callbacks are defined and async
3. Ensure the parent updates `approvalBannerState` to `null` after approval succeeds
4. Open DevTools and log the state prop to verify its current value

### Q: Governance tab in activity feed is empty

**A**:
1. Verify `permissionStages` prop is being passed with data
2. Check the shape of each stage object matches: `{ name, status, timestamp? }`
3. If governance info comes from API, ensure it's loaded before rendering
4. If no governance info, omit the prop — component gracefully handles undefined

### Q: Components compile but page is blank/broken

**A**:
1. Check browser console for JavaScript errors
2. Check that all imports resolve (files exist, paths are correct)
3. Verify component exports are named correctly (not default exports)
4. Run TypeScript check: `npx tsc --noEmit`

---

## Next Steps

After successful integration:

1. **Commit changes**: Create a PR with the component swap
2. **Test with real data**: Run actual project + run to verify UI works with real events
3. **Gather feedback**: Have team review the new visual design
4. **Iterate**: Adjust colors, spacing, or density based on feedback
5. **Deploy**: Once approved, merge to main and deploy

---

## Support

For detailed implementation examples, see:

- `RunStudioLayout.tsx` — Fully wired example component (reference only)
- `ApprovalBanner.tsx` — Original component (for comparison)
- `ToolActivityFeed.tsx` — Original component (reference for event grouping logic)

For questions about specific events or data structures, see:

- `lib/runEvents.ts` — Event type definitions
- `lib/runTodosFromEvents.ts` — Todo parsing logic
- `hooks/useRunStudio.tsx` — Hook that provides all props
