"use client";

import { Button } from "@/components/ui/Button";
import { ApprovalBannerState } from "./ApprovalBanner";

/**
 * ApprovalBannerRedesigned — enhanced approval gate with improved visual hierarchy.
 *
 * Redesigned version of ApprovalBanner with:
 * - Clearer status colors using new semantic tokens (--status-ok, --status-warn, --status-error)
 * - Better icon/text alignment
 * - Animated loading state
 * - Enhanced accessibility
 *
 * Accepts the same state prop as the original ApprovalBanner for drop-in replacement.
 */
export function ApprovalBannerRedesigned({ state }: { state: ApprovalBannerState }) {
  if (!state) return null;

  const isReviewReady = state.type === "review_ready";
  const isHitlGate = state.type === "hitl_gate";
  const isPlanBlocked = state.type === "plan_blocked";

  // Status-specific styling
  const statusConfig = isHitlGate
    ? {
        bgColor: "bg-[#FEF3E2]",
        borderColor: "border-[#B8651A]",
        textColor: "text-[#B8651A]",
        accentColor: "var(--status-warn)",
        icon: "⚠️",
      }
    : isReviewReady
      ? {
          bgColor: "bg-[#E8F5E9]",
          borderColor: "border-[#2D7A3B]",
          textColor: "text-[#2D7A3B]",
          accentColor: "var(--status-ok)",
          icon: "✓",
        }
      : {
          bgColor: "bg-[#FFEBEE]",
          borderColor: "border-[#B23C3C]",
          textColor: "text-[#B23C3C]",
          accentColor: "var(--status-error)",
          icon: "⊘",
        };

  const primaryLabel = isReviewReady
    ? state.busy
      ? "Submitting…"
      : "Final Approve"
    : isPlanBlocked
      ? "Blocked"
      : "Approve";

  return (
    <div
      className={`sticky bottom-0 z-20 border-t-2 ${statusConfig.bgColor} ${statusConfig.borderColor} px-4 py-4 shadow-[0_-2px_12px_rgba(0,0,0,0.08)]`}
      role="status"
      aria-live="assertive"
      aria-atomic="true"
      aria-label={`${state.type} approval state`}
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
          style={{ backgroundColor: statusConfig.accentColor, opacity: 0.15 }}
        >
          <span className="text-sm" aria-hidden="true">
            {statusConfig.icon}
          </span>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {isHitlGate && (
            <>
              <p className={`text-sm font-semibold ${statusConfig.textColor}`}>Approval required</p>
              <p className="mt-1 text-xs text-[#666] line-clamp-2">{state.reason}</p>
            </>
          )}
          {isReviewReady && (
            <>
              <p className={`text-sm font-semibold ${statusConfig.textColor}`}>
                Outputs ready for review
              </p>
              <p className="mt-1 text-xs text-[#666]">
                Review evidence claims on the Deck tab, then approve to run guardrails and finalize.
              </p>
            </>
          )}
          {isPlanBlocked && (
            <>
              <p className={`text-sm font-semibold ${statusConfig.textColor}`}>
                Governance check failed
              </p>
              <p className="mt-1 text-xs text-[#666]">
                {state.blockedStage ? `Stage: ${state.blockedStage}` : "Stage: unknown"}
                {state.blockedCode ? ` (${state.blockedCode})` : ""}
                {state.blockedReason ? ` — ${state.blockedReason}` : ""}
              </p>
            </>
          )}
        </div>

        {/* Action Button */}
        <div className="ml-auto flex shrink-0 items-center">
          {isPlanBlocked ? (
            <Button
              type="button"
              variant="secondary"
              disabled={!state.onResimulate}
              onClick={() => void state.onResimulate?.()}
              aria-label="Re-run preflight checks"
            >
              Re-run
            </Button>
          ) : (
            <Button
              type="button"
              disabled={isReviewReady && state.busy}
              onClick={() => void state.onApprove()}
              aria-label={primaryLabel}
              className={isReviewReady && state.busy ? "opacity-75" : ""}
            >
              {isReviewReady && state.busy ? (
                <span className="inline-flex items-center gap-2">
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  {primaryLabel}
                </span>
              ) : (
                primaryLabel
              )}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
