"use client";

import { Button } from "@/components/ui/Button";

export function ZoneBPlanReview({
  runStatus,
  saving,
  onSave,
  onApprove,
}: {
  runStatus: string | null;
  saving: boolean;
  onSave: () => Promise<void>;
  onApprove: () => Promise<void>;
}) {
  if (runStatus !== "plan_ready") return null;

  return (
    <div className="rounded-lg border p-4 status-surface--queued">
      <p className="text-sm">
        Plan is ready for sign-off. The agent will not execute significant actions until you approve.
      </p>
      <div className="mt-2 flex gap-2">
        <Button variant="secondary" disabled={saving} onClick={() => void onSave()}>
          {saving ? "Saving..." : "Save plan changes"}
        </Button>
        <Button disabled={saving} onClick={() => void onApprove()}>
          Approve & Run
        </Button>
      </div>
    </div>
  );
}
