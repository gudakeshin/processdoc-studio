"use client";

import { useState } from "react";
import { AlertTriangle, Clock, Loader2, OctagonX, PauseCircle, PlayCircle, RotateCcw } from "lucide-react";

import { Card } from "@/components/ui/Card";
import { ActivityFeedRedesigned } from "@/components/run-studio/ActivityFeedRedesigned";
import {
  useActiveRunsQuery,
  useRunControlMutation,
  type ActiveRunRow,
  type ActiveRunState,
} from "@/hooks/useActiveRuns";
import { useRunsQuery } from "@/hooks/useRuns";
import {
  useDeadLetterQueueQuery,
  useReplayDeadLetterMutation,
  useResetDeadLetterAttemptsMutation,
} from "@/hooks/useDeadLetterQueue";
import { useRunStream } from "@/hooks/useRunStream";
import { runTodosFromEvents } from "@/lib/runTodosFromEvents";
import { formatCostCompact, formatTokenCount } from "@/lib/formatTokens";

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

function ActiveRunRowItem({
  run,
  selected,
  onSelect,
  onControl,
  busyAction,
}: {
  run: ActiveRunRow;
  selected: boolean;
  onSelect: () => void;
  onControl: (action: "pause" | "resume" | "stop") => void;
  busyAction: "pause" | "resume" | "stop" | null;
}) {
  const canPause = run.status === "approved";
  const canResume = run.status === "plan_ready";
  const canStop = run.status !== "done" && run.status !== "failed";

  return (
    <li
      className={`border p-3 text-xs ${
        selected ? "border-[var(--accent-blue)] bg-[var(--surface-muted)]" : "border-[var(--surface-border)] bg-white"
      }`}
    >
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
        onClick={onSelect}
        title={run.instruction}
      >
        {run.id}
      </button>
      <p className="mt-0.5 truncate text-[var(--text-muted)]" title={run.instruction}>
        {run.instruction || "—"}
      </p>
      <p className="mt-0.5 text-[var(--text-muted)]">
        {formatTokenCount(run.tokens_input ?? 0)} in / {formatTokenCount(run.tokens_output ?? 0)} out ·{" "}
        {formatCostCompact(run.cost_usd)}
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {canPause ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 border border-[var(--surface-border)] px-1.5 py-0.5 text-[11px] font-medium hover:bg-[var(--surface-muted)] disabled:opacity-50"
            onClick={() => onControl("pause")}
            disabled={busyAction !== null}
          >
            {busyAction === "pause" ? <Loader2 size={11} className="animate-spin" /> : <PauseCircle size={11} />}
            Pause
          </button>
        ) : null}
        {canResume ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 border border-[var(--surface-border)] px-1.5 py-0.5 text-[11px] font-medium hover:bg-[var(--surface-muted)] disabled:opacity-50"
            onClick={() => onControl("resume")}
            disabled={busyAction !== null}
          >
            {busyAction === "resume" ? <Loader2 size={11} className="animate-spin" /> : <PlayCircle size={11} />}
            Resume
          </button>
        ) : null}
        {canStop ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 border border-[#B23C3C] px-1.5 py-0.5 text-[11px] font-medium text-[#B23C3C] hover:bg-[#FFEBEE] disabled:opacity-50"
            onClick={() => onControl("stop")}
            disabled={busyAction !== null}
          >
            {busyAction === "stop" ? <Loader2 size={11} className="animate-spin" /> : <OctagonX size={11} />}
            Stop
          </button>
        ) : null}
      </div>
    </li>
  );
}

function DeadLetterSection({ projectId }: { projectId: string }) {
  const { data, isLoading } = useDeadLetterQueueQuery(projectId);
  const replay = useReplayDeadLetterMutation(projectId);
  const resetAttempts = useResetDeadLetterAttemptsMutation(projectId);
  const items = data ?? [];

  if (isLoading) {
    return <p className="text-xs text-[var(--text-muted)]">Loading dead-letter queue…</p>;
  }
  if (items.length === 0) {
    return <p className="text-xs text-[var(--text-muted)]">No stuck queue items.</p>;
  }

  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.id ?? item.run_id} className="border border-[var(--surface-border)] bg-white p-2 text-xs">
          <p className="font-mono text-[11px]">{item.run_id ?? item.id}</p>
          <p className="mt-0.5 text-[var(--text-muted)]">{item.reason || item.status || "Unknown failure"}</p>
          {item.replay_blocked_reason ? (
            <p className="mt-0.5 text-[#B23C3C]">Blocked: {item.replay_blocked_reason}</p>
          ) : null}
          {typeof item.replay_attempts === "number" ? (
            <p className="mt-0.5 text-[var(--text-muted)]">Replay attempts: {item.replay_attempts}</p>
          ) : null}
          <div className="mt-1.5 flex gap-1.5">
            <button
              type="button"
              className="inline-flex items-center gap-1 border border-[var(--surface-border)] px-1.5 py-0.5 text-[11px] font-medium hover:bg-[var(--surface-muted)] disabled:opacity-50"
              onClick={() => item.id && replay.mutate(item.id)}
              disabled={replay.isPending}
            >
              <RotateCcw size={11} />
              Replay
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 border border-[var(--surface-border)] px-1.5 py-0.5 text-[11px] font-medium hover:bg-[var(--surface-muted)] disabled:opacity-50"
              onClick={() => item.id && resetAttempts.mutate(item.id)}
              disabled={resetAttempts.isPending}
            >
              Reset attempts
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function SelectedRunActivity({ projectId, runId }: { projectId: string; runId: string }) {
  const { events, parsedEvents } = useRunStream(projectId, runId);
  const runTodos = runTodosFromEvents(events);
  return (
    <ActivityFeedRedesigned parsedEvents={parsedEvents} artifacts={[]} runTodos={runTodos} width={420} />
  );
}

export function AgentOpsView({ projectId }: { projectId: string }) {
  const activeRunsQuery = useActiveRunsQuery(projectId);
  const recentRunsQuery = useRunsQuery(projectId);
  const controlMutation = useRunControlMutation(projectId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [busyRunAction, setBusyRunAction] = useState<{ runId: string; action: "pause" | "resume" | "stop" } | null>(
    null
  );

  const activeRuns = activeRunsQuery.data?.items ?? [];
  const recentRuns = recentRunsQuery.data ?? [];

  async function handleControl(runId: string, action: "pause" | "resume" | "stop") {
    setBusyRunAction({ runId, action });
    try {
      await controlMutation.mutateAsync({ runId, action });
    } finally {
      setBusyRunAction(null);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <div className="space-y-4">
        <Card className="p-3">
          <h2 className="text-sm font-semibold text-[var(--text-default)]">Active runs</h2>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            In-flight runs for this project — working, queued, blocked, or stuck.
          </p>
          <div className="mt-3">
            {activeRunsQuery.isLoading ? (
              <p className="text-xs text-[var(--text-muted)]">Loading run health…</p>
            ) : activeRunsQuery.error ? (
              <p className="text-xs text-[#B23C3C]">{(activeRunsQuery.error as Error).message}</p>
            ) : activeRuns.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">No active runs.</p>
            ) : (
              <ul className="space-y-2">
                {activeRuns.map((run) => (
                  <ActiveRunRowItem
                    key={run.id}
                    run={run}
                    selected={run.id === selectedRunId}
                    onSelect={() => setSelectedRunId(run.id)}
                    onControl={(action) => void handleControl(run.id, action)}
                    busyAction={busyRunAction?.runId === run.id ? busyRunAction.action : null}
                  />
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card className="p-3">
          <h2 className="text-sm font-semibold text-[var(--text-default)]">Recent runs</h2>
          <div className="mt-3">
            {recentRunsQuery.isLoading ? (
              <p className="text-xs text-[var(--text-muted)]">Loading…</p>
            ) : recentRuns.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">No runs yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {recentRuns.slice(0, 20).map((run) => (
                  <li key={run.id}>
                    <button
                      type="button"
                      className={`block w-full truncate border border-[var(--surface-border)] bg-white p-2 text-left text-xs hover:bg-[var(--surface-muted)] ${
                        run.id === selectedRunId ? "border-[var(--accent-blue)]" : ""
                      }`}
                      onClick={() => setSelectedRunId(run.id)}
                      title={run.instruction}
                    >
                      <span className="font-mono text-[11px] text-[var(--accent-blue)]">{run.id}</span>
                      <span className="ml-2 text-[var(--text-muted)]">{run.status}</span>
                      <p className="mt-0.5 truncate text-[var(--text-muted)]">{run.instruction || "—"}</p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card className="p-3">
          <h2 className="text-sm font-semibold text-[var(--text-default)]">Dead-letter queue</h2>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            Runs the worker gave up on — replay once the underlying issue is fixed, or reset attempts.
          </p>
          <div className="mt-3">
            <DeadLetterSection projectId={projectId} />
          </div>
        </Card>
      </div>

      <Card className="p-3">
        <h2 className="text-sm font-semibold text-[var(--text-default)]">Live activity</h2>
        {selectedRunId ? (
          <div className="mt-3">
            <SelectedRunActivity projectId={projectId} runId={selectedRunId} />
          </div>
        ) : (
          <p className="mt-3 text-xs text-[var(--text-muted)]">
            Select a run on the left to watch its live activity feed.
          </p>
        )}
      </Card>
    </div>
  );
}
