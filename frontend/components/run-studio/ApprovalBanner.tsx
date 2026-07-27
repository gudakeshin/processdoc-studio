"use client";

import { Button } from "@/components/ui/Button";

export type ApprovalBannerState =
  | {
      type: "hitl_gate";
      reason: string;
      onApprove: () => Promise<void>;
    }
  | {
      type: "review_ready";
      busy: boolean;
      onApprove: () => Promise<void>;
    }
  | {
      type: "plan_blocked";
      blockedStage?: string;
      blockedReason?: string;
      blockedCode?: string;
      onResimulate?: () => Promise<void>;
    }
  | null;

/**
 * ApprovalBanner — unified, non-modal approval gate.
 *
 * Sits sticky at the bottom of the conversation column. Handles two approval
 * checkpoints:
 *   hitl_gate    → mid-run approval requested by the Digital Teammate
 *   review_ready → final approval to run guardrails after output generation
 * plan_blocked shows a governance error with a re-simulate option.
 */
export function ApprovalBanner({ state }: { state: ApprovalBannerState }) {
  if (!state) return null;

  const isReviewReady = state.type === "review_ready";
  const isHitlGate = state.type === "hitl_gate";
  const isPlanBlocked = state.type === "plan_blocked";

  const primaryLabel = isReviewReady
    ? (state.busy ? "Submitting…" : "Final Approve")
    : isPlanBlocked
      ? "Blocked"
      : "Approve";

  return (
    <div className="sticky bottom-0 z-20 rounded-b-lg border-t border-[color:color-mix(in_srgb,var(--warning)_30%,white)] bg-[var(--warning-light)] px-4 py-3 shadow-[0_-2px_8px_rgba(0,0,0,0.06)]">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          {isHitlGate && (
            <>
              <p className="text-sm font-semibold text-[color:color-mix(in_srgb,var(--warning)_82%,black)]">Approval required</p>
              <p className="mt-0.5 text-xs text-[color:color-mix(in_srgb,var(--warning)_74%,black)]">{state.reason}</p>
            </>
          )}
          {isReviewReady && (
            <>
              <p className="text-sm font-semibold text-[color:color-mix(in_srgb,var(--warning)_82%,black)]">
                Outputs ready — final review
              </p>
              <p className="mt-0.5 text-xs text-[color:color-mix(in_srgb,var(--warning)_74%,black)]">
                Review evidence claims on the Deck tab, then approve to run guardrails.
              </p>
            </>
          )}
          {isPlanBlocked && (
            <>
              <p className="text-sm font-semibold text-[var(--error)]">
                Plan blocked by automated governance checks
              </p>
              <p className="mt-0.5 text-xs text-[color:color-mix(in_srgb,var(--error)_82%,black)]">
                {state.blockedStage ? `Stage: ${state.blockedStage}` : "Stage: unknown"}{" "}
                {state.blockedCode ? `(${state.blockedCode})` : ""}{" "}
                {state.blockedReason ? `— ${state.blockedReason}` : ""}
              </p>
            </>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {isPlanBlocked ? (
            <Button
              type="button"
              variant="secondary"
              disabled={!state.onResimulate}
              onClick={() => void state.onResimulate?.()}
            >
              Re-run preflight
            </Button>
          ) : (
            <Button
              type="button"
              disabled={isReviewReady && state.busy}
              onClick={() => void state.onApprove()}
            >
              {primaryLabel}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
