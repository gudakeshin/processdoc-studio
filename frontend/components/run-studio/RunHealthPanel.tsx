"use client";

import { AlertTriangle, Clock, Loader2, OctagonX } from "lucide-react";

import {
  useActiveRunsQuery,
  useStopRunMutation,
  type ActiveRunRow,
  type ActiveRunState,
} from "@/hooks/useActiveRuns";

/**
 * RunHealthPanel — agentops view of every in-flight run for a project.
 *
 * Distinguishes a hung run (status=running, no events past the stuck threshold) from one
 * merely awaiting your approval or queued behind a busy worker, and offers a force-stop that
 * frees the admission slot. Pairs with the backend stuck-run watchdog which auto-fails hung
 * runs on its own; this panel is the manual/visibility surface.
 */

const STATE_LABEL: Record<ActiveRunState, string> = {
  working: "Working",
  hung: "Hung — no progress",
  awaiting_approval: "Awaiting your approval",
  blocked: "Blocked by policy",
  queued: "Queued",
};

const STATE_CLASS: Record<ActiveRunState, string> = {
  working: "bg-[#E3F2FD] text-[#0072B1]",
  hung: "bg-[#FFEBEE] text-[#B23C3C]",
  awaiting_approval: "bg-[#FEF3E2] text-[#B8651A]",
  blocked: "bg-[#FFEBEE] text-[#B23C3C]",
  queued: "bg-[var(--surface-muted)] text-[var(--text-muted)]",
};

function formatAge(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 360) / 10}h`;
}

function RunRow({
  run,
  onSelectRun,
  onStop,
  stopping,
}: {
  run: ActiveRunRow;
  onSelectRun?: (runId: string) => void;
  onStop: (runId: string) => void;
  stopping: boolean;
}) {
  const stoppable = run.status === "running" || run.status === "approved";
  return (
    <li className="border border-[var(--surface-border)] bg-white p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 font-medium ${STATE_CLASS[run.state]}`}>
          {run.state === "hung" ? <AlertTriangle size={11} /> : null}
          {run.state === "working" ? <Loader2 size={11} className="animate-spin" /> : null}
          {STATE_LABEL[run.state]}
        </span>
        <span className="inline-flex items-center gap-1 text-[var(--text-muted)]" title="Time since last audit event">
          <Clock size={11} />
          {formatAge(run.seconds_since_last_event)}
        </span>
      </div>
      <button
        type="button"
        className="mt-1 block w-full truncate text-left font-mono text-[11px] text-[var(--accent-blue)] hover:underline"
        onClick={() => onSelectRun?.(run.id)}
        title={run.instruction}
      >
        {run.id}
      </button>
      <p className="mt-0.5 truncate text-[var(--text-muted)]" title={run.instruction}>
        {run.instruction || "—"}
      </p>
      {stoppable ? (
        <button
          type="button"
          className="mt-1.5 inline-flex items-center gap-1 border border-[#B23C3C] px-1.5 py-0.5 text-[11px] font-medium text-[#B23C3C] hover:bg-[#FFEBEE] disabled:opacity-50"
          onClick={() => onStop(run.id)}
          disabled={stopping}
        >
          {stopping ? <Loader2 size={11} className="animate-spin" /> : <OctagonX size={11} />}
          Stop
        </button>
      ) : null}
    </li>
  );
}

export function RunHealthPanel({
  projectId,
  onSelectRun,
}: {
  projectId: string;
  onSelectRun?: (runId: string) => void;
}) {
  const { data, isLoading, error } = useActiveRunsQuery(projectId);
  const stopMutation = useStopRunMutation(projectId);
  const items = data?.items ?? [];

  if (isLoading) {
    return <p className="text-xs text-[var(--text-muted)]">Loading run health…</p>;
  }
  if (error) {
    return <p className="text-xs text-[#B23C3C]">{(error as Error).message}</p>;
  }
  if (items.length === 0) {
    return <p className="text-xs text-[var(--text-muted)]">No active runs.</p>;
  }

  return (
    <ul className="space-y-2">
      {items.map((run) => (
        <RunRow
          key={run.id}
          run={run}
          onSelectRun={onSelectRun}
          onStop={(rid) => stopMutation.mutate(rid)}
          stopping={stopMutation.isPending && stopMutation.variables === run.id}
        />
      ))}
    </ul>
  );
}
