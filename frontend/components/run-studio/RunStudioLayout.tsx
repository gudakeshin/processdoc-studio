"use client";

/**
 * RunStudioLayout — Reference example for integrating redesigned components
 *
 * This file shows how to integrate the new ApprovalBannerRedesigned,
 * ActivityFeedRedesigned, and SystemBanner components into RunStudioView.
 *
 * It demonstrates:
 * 1. Component imports and basic wiring
 * 2. State management for density/accent themes (commented out)
 * 3. Prop mapping from UseRunStudioReturn to new components
 * 4. Layout structure with proper spacing and responsive behavior
 *
 * Copy patterns from this file into your actual RunStudioView.tsx
 */

import type { UseRunStudioReturn } from "@/hooks/useRunStudio";
import { ApprovalBannerRedesigned } from "./ApprovalBannerRedesigned";
import { ActivityFeedRedesigned } from "./ActivityFeedRedesigned";
import { SystemBanner } from "./SystemBanner";

export function RunStudioLayoutExample(props: UseRunStudioReturn) {
  // Optional: Uncomment to add density/accent theme toggles
  // const [density, setDensity] = useState<"comfortable" | "compact">("comfortable");
  // const [accentColor, setAccentColor] = useState<"green" | "blue" | "black" | "amber">("green");

  return (
    <div
      className="min-h-screen bg-white"
      // Optional: Apply density and accent data attributes
      // data-density={density}
      // data-accent={accentColor}
    >
      {/* ===================================================================
          SECTION 1: Top bar with system banners and status
          ==================================================================== */}

      <div className="sticky top-0 z-40 border-b border-[#E0E0E0] bg-white">
        {/* System banners for warnings/info */}
        {props.pollMode && (
          <SystemBanner
            type="info"
            title="Polling mode active"
            detail="Stream connection lost. The system is polling for updates every 5 seconds."
            action={{
              label: "Reconnect now",
              onClick: () => {
                // Trigger reconnection logic
              },
            }}
          />
        )}

        {props.approvalBannerState?.type === "plan_blocked" && (
          <SystemBanner
            type="error"
            title="Governance checks failed"
            detail={props.approvalBannerState.blockedReason || "One or more automated checks did not pass."}
            action={{
              label: "View details",
              onClick: () => {
                // Show governance details
              },
            }}
          />
        )}

        {props.streamError && (
          <SystemBanner
            type="warn"
            title="Stream error"
            detail={props.streamError}
            dismissible={true}
          />
        )}
      </div>

      {/* ===================================================================
          SECTION 2: Main layout (left conversation + right sidebar)
          ==================================================================== */}

      <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* LEFT COLUMN: Conversation and content */}
        <section className="relative flex min-h-screen flex-col gap-3 px-4 py-4">
          {/* Chat messages / instruction zone */}
          <div className="flex-1 overflow-y-auto space-y-4">
            {/* Render your chat messages here */}
            {/* Example:
              {props.instructionChatMessages.map((msg) => (
                <div key={msg.id} className="...">
                  {msg.content}
                </div>
              ))}
            */}
          </div>

          {/* Approval banner — sticky at bottom */}
          <div className="sticky bottom-0 z-20">
            <ApprovalBannerRedesigned state={props.approvalBannerState} />
          </div>

          {/* Chat input / composer */}
          <div className="pt-4 border-t border-[#E0E0E0]">
            {/* Render your textarea and send button here */}
            {/* Example:
              <textarea
                value={props.chatInput}
                onChange={(e) => props.setChatInput(e.target.value)}
                placeholder="Type your instruction..."
              />
              <button onClick={() => props.sendChatMessage()}>
                Send
              </button>
            */}
          </div>
        </section>

        {/* RIGHT SIDEBAR: Activity feed (360px) */}
        <aside className="hidden min-h-screen xl:flex flex-col">
          <ActivityFeedRedesigned
            parsedEvents={props.parsedRunEvents}
            artifacts={props.artifacts?.ready_downloads || []}
            runTodos={props.runChecklistTodos || []}
            contextMetadata={{
              leadingPractices: [
                "Use consistent naming conventions",
                "Follow the style guide provided",
              ],
              nonNegotiables: [
                "Brand colors must match guidelines",
                "Font sizes and spacing must use design tokens",
              ],
            }}
            permissionStages={
              // Example permission/governance stages
              [
                {
                  name: "PII Check",
                  status: "approved" as const,
                  timestamp: "2 min ago",
                },
                {
                  name: "Content Review",
                  status: "pending" as const,
                },
              ]
            }
            width={360}
          />
        </aside>
      </div>

      {/* ===================================================================
          SECTION 3: Optional tweaks panel (for theme development)
          ==================================================================== */}

      {/* Uncomment to enable density/accent toggle panel during development

      <div className="fixed bottom-4 left-4 z-50 bg-white border border-[#E0E0E0] rounded p-4 shadow-lg">
        <p className="text-xs font-semibold mb-3">Tweaks (dev only)</p>

        <div className="space-y-2">
          <div>
            <label className="text-2xs font-medium">Density</label>
            <select
              value={density}
              onChange={(e) => setDensity(e.target.value as any)}
              className="block w-full text-xs mt-1 border border-[#E0E0E0] rounded px-2 py-1"
            >
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </select>
          </div>

          <div>
            <label className="text-2xs font-medium">Accent</label>
            <select
              value={accentColor}
              onChange={(e) => setAccentColor(e.target.value as any)}
              className="block w-full text-xs mt-1 border border-[#E0E0E0] rounded px-2 py-1"
            >
              <option value="green">Green (default)</option>
              <option value="blue">Blue</option>
              <option value="black">Black</option>
              <option value="amber">Amber</option>
            </select>
          </div>
        </div>
      </div>

      */}
    </div>
  );
}
