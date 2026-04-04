"use client";

import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import React, { useMemo, useState } from "react";
import { AgentStatusGraph } from "@/components/run-studio/AgentStatusGraph";
import { TodoChecklist } from "@/components/run-studio/TodoChecklist";
import { useTodoChecklistState } from "@/hooks/useTodoChecklistState";
import { toolCallsFromAgentRoundPayload } from "@/lib/agentToolRound";
import type { ParsedRunEvent } from "@/lib/runEvents";
import type { RunTodoRow } from "@/lib/runTodosFromEvents";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToolCall = {
  name: string;
  status: "running" | "done" | "failed";
  summary: string;
};

type SkillGroup = {
  key: string;
  skillName: string;
  status: "running" | "done" | "failed" | "queued";
  tools: ToolCall[];
};

// ---------------------------------------------------------------------------
// Event parsing helpers
// ---------------------------------------------------------------------------

function parseEventLine(line: string): {
  eventType: string;
  payloadObj: Record<string, unknown> | null;
} {
  const sep = line.indexOf(":");
  const eventType = (sep >= 0 ? line.slice(0, sep) : "step").trim();
  const payloadText = (sep >= 0 ? line.slice(sep + 1) : line).trim();
  let payloadObj: Record<string, unknown> | null = null;
  try {
    const parsed = JSON.parse(payloadText);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      payloadObj = parsed as Record<string, unknown>;
    }
  } catch {
    /* ignore unparseable payloads */
  }
  return { eventType, payloadObj };
}

/** Strict run-events-v1 stores fields under `payload`; merge so `status`, `agent`, etc. are visible. */
function mergeRunEventPayload(p: Record<string, unknown> | null): Record<string, unknown> {
  if (!p) return {};
  const inner = p.payload;
  if (inner && typeof inner === "object" && !Array.isArray(inner)) {
    return { ...p, ...(inner as Record<string, unknown>) };
  }
  return p;
}

function buildSkillGroups(events: string[]): SkillGroup[] {
  const groups: SkillGroup[] = [];
  const groupIndex: Record<string, number> = {};
  let queueSeen = false;
  let executionStarted = false;

  // Coordinator plan as first group if present
  for (const line of events) {
    const { eventType, payloadObj: p } = parseEventLine(line);
    if ((eventType === "coordinator_plan" || eventType === "execution_plan") && p) {
      const ep = mergeRunEventPayload(p);
      const plannedOutputs = Array.isArray(ep.planned_outputs)
        ? (ep.planned_outputs as string[])
        : [];
      if (plannedOutputs.length > 0 && !("__coordinator__" in groupIndex)) {
        groupIndex["__coordinator__"] = groups.length;
        groups.push({
          key: "__coordinator__",
          skillName: "Coordinator",
          status: "done",
          tools: plannedOutputs.map((o) => ({
            name: o,
            status: "done" as const,
            summary: String((ep.per_output_notes as Record<string, unknown>)?.[o] ?? "planned"),
          })),
        });
      }
    }
  }

  // Skill + tool events
  for (const line of events) {
    const { eventType, payloadObj: p } = parseEventLine(line);

    // "step" events carry skill execution progress
    if (eventType === "step" && p) {
      const ep = mergeRunEventPayload(p);
      const raw = String(ep.status ?? "");
      if (raw === "execution_enqueued") {
        queueSeen = true;
      }
      if (raw === "execution_started") {
        executionStarted = true;
      }
      const skillName = String(
        ep.skill_name ?? ep.agent ?? ep.output_type ?? ep.step ?? "Agent"
      );
      const key = skillName.toLowerCase().replace(/\s+/g, "_");

      if (!(key in groupIndex)) {
        groupIndex[key] = groups.length;
        groups.push({
          key,
          skillName,
          status: "queued",
          tools: [],
        });
      }

      const g = groups[groupIndex[key]];
      if (raw.includes("fail") || raw.includes("error")) {
        g.status = "failed";
      } else if (
        raw.includes("post_processing_done") ||
        (raw.includes("processing_done") && raw.includes("post"))
      ) {
        g.status = "done";
      } else if (
        raw.includes("done") ||
        raw.includes("complet") ||
        raw.includes("finish")
      ) {
        g.status = "done";
      } else if (
        raw.includes("post_processing_start") ||
        (raw.includes("post_processing") && !raw.includes("done"))
      ) {
        g.status = "running";
      } else if (raw.includes("start") || raw.includes("run")) {
        g.status = "running";
      }
    }

    // "agent_tool_round" events carry tool call details (backend: trace[].tool per tool_use)
    if (eventType === "agent_tool_round" && p) {
      const ep = mergeRunEventPayload(p);
      const skillName = String(
        ep.skill_name ?? ep.agent ?? ep.output_type ?? "Agent"
      );
      const key = skillName.toLowerCase().replace(/\s+/g, "_");
      const rows = toolCallsFromAgentRoundPayload(ep);
      const roundLabel =
        typeof ep.round === "number" ? `Round ${ep.round}` : "";

      // Create a group if not yet seen (tool round may arrive before the step)
      if (!(key in groupIndex)) {
        groupIndex[key] = groups.length;
        groups.push({ key, skillName, status: "running", tools: [] });
      }
      const g = groups[groupIndex[key]];
      if (rows.length === 0) {
        g.tools.push({
          name: "tool round",
          status: "done",
          summary: roundLabel
            ? `No tool names in payload · ${roundLabel}`
            : "No tool names in event payload",
        });
      } else {
        rows.forEach((row, idx) => {
          const parts = [row.summary, idx === 0 ? roundLabel : ""].filter(Boolean);
          g.tools.push({
            name: row.name,
            status: "done",
            summary: parts.join(" · "),
          });
        });
      }
    }
  }

  // Only show the synthetic queue row while enqueued but before the worker has started execution.
  if (queueSeen && !executionStarted && !groups.some((g) => g.key === "__queue__")) {
    groups.unshift({
      key: "__queue__",
      skillName: "Run queue",
      status: "queued",
      tools: [
        {
          name: "Queued for execution worker",
          status: "running",
          summary:
            "The run is in the queue until a worker process picks it up and starts the agent.",
        },
      ],
    });
  }

  return groups;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function GroupStatusIcon({ status }: { status: SkillGroup["status"] }) {
  const c = "h-3.5 w-3.5 shrink-0";
  if (status === "running") return <Loader2 className={`${c} animate-spin`} aria-hidden />;
  if (status === "done") return <CheckCircle2 className={c} aria-hidden />;
  if (status === "failed") return <XCircle className={c} aria-hidden />;
  return <CircleDashed className={c} aria-hidden />;
}

function StatusBadge({ status }: { status: SkillGroup["status"] }) {
  const cls =
    status === "running"
      ? "status-pill--info"
      : status === "done"
      ? "status-pill--success"
      : status === "failed"
      ? "status-pill--error"
      : "bg-[var(--surface-muted)] text-[var(--text-muted)]";
  return (
    <span className={`status-pill inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide ${cls}`}>
      <GroupStatusIcon status={status} />
      {status}
    </span>
  );
}

function ToolStatusIcon({ status }: { status: ToolCall["status"] }) {
  const c = "mt-0.5 h-3.5 w-3.5 shrink-0";
  if (status === "running") return <Loader2 className={`${c} animate-spin text-[var(--info)]`} aria-hidden />;
  if (status === "done") return <CheckCircle2 className={`${c} text-[var(--success)]`} aria-hidden />;
  return <XCircle className={`${c} text-[var(--error)]`} aria-hidden />;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * ToolActivityFeed — right-panel live tool activity and context.
 *
 * Replaces the static Context Inspector sidebar. Three tabs:
 *   Activity  → live skill groups with nested tool calls
 *   Artifacts → ready download badges + download buttons (via downloadsContent slot)
 *   Context   → LP snippets, memory non-negotiables
 */
export function ToolActivityFeed({
  events,
  parsedEvents,
  runChecklistTodos,
  artifacts,
  pollMode,
  streamError,
  onTaskAction,
  downloadsContent,
  showAgentGraph = true,
  hooksPanel,
  permissionPanel,
}: {
  events: string[];
  parsedEvents?: ParsedRunEvent[];
  runChecklistTodos?: RunTodoRow[];
  artifacts: any;
  pollMode: boolean;
  streamError: string | null;
  showAgentGraph?: boolean;
  /** Render slot for download buttons — passed from the parent with full artifact access */
  downloadsContent?: React.ReactNode;
  onTaskAction?: (taskId: string, action: "retry" | "skip" | "approve") => void;
  hooksPanel?: {
    hooks: Array<Record<string, unknown>>;
    loading: boolean;
    onRefresh: () => void;
    onDisable: (hookName: string, reason: string) => void;
  };
  permissionPanel?: {
    busy: boolean;
    result: any | null;
    onSimulate: () => void;
  };
}) {
  const [activeTab, setActiveTab] = useState<"activity" | "artifacts" | "context" | "governance">(
    "activity"
  );
  const [disableReason, setDisableReason] = useState("");

  const skillGroups = useMemo(() => buildSkillGroups(events), [events]);
  const checklist = useTodoChecklistState({
    parsedEvents: parsedEvents ?? [],
    snapshotRows: runChecklistTodos ?? [],
  });

  const readyDownloads: string[] = Array.isArray(artifacts?.ready_downloads)
    ? artifacts.ready_downloads.map((x: unknown) => String(x))
    : [];

  const outputFilenames: Record<string, string> = useMemo(() => {
    if (!artifacts?.output_filenames || typeof artifacts.output_filenames !== "object") return {};
    return artifacts.output_filenames as Record<string, string>;
  }, [artifacts?.output_filenames]);

  const readyDownloadFilenames = useMemo(
    () =>
      readyDownloads
        .map((d) => outputFilenames[d])
        .filter((n): n is string => Boolean(n && String(n).trim())),
    [readyDownloads, outputFilenames]
  );

  const hasArtifactDownloads = readyDownloads.length > 0 || Boolean(downloadsContent);

  const lpSnippets: string[] = useMemo(() => {
    const ctx =
      typeof artifacts?.assembled_context === "string"
        ? artifacts.assembled_context
        : "";
    if (!ctx) return [];
    return ctx
      .split("\n[LP]")
      .map((chunk: string, idx: number) => (idx === 0 ? chunk : `[LP]${chunk}`))
      .filter((chunk: string) => chunk.trim().startsWith("[LP]"))
      .slice(0, 4);
  }, [artifacts?.assembled_context]);

  const memorySummary = artifacts?.memory_summary as
    | {
        non_negotiables?: string[];
        recent_changes?: Array<{
          event_type?: string;
          payload?: { summary?: string };
        }>;
      }
    | undefined;

  const runningGroup = skillGroups.find((g) => g.status === "running");
  const queuedGroup = !runningGroup ? skillGroups.find((g) => g.status === "queued") : null;
  const latestRecovery = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const line = events[i];
      if (!line.startsWith("recovery_mode:")) continue;
      const raw = line.slice("recovery_mode:".length).trim();
      try {
        const obj = JSON.parse(raw) as Record<string, unknown>;
        return {
          mode: typeof obj.mode === "string" ? obj.mode : "unknown",
          attempt: typeof obj.attempt === "number" ? obj.attempt : null,
        };
      } catch {
        return { mode: "unknown", attempt: null };
      }
    }
    return null;
  }, [events]);
  const heartbeatSeen = useMemo(() => events.some((x) => x.startsWith("heartbeat:")), [events]);

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-[var(--surface-border)] bg-white shadow-sm">
      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b border-[var(--surface-border)] px-3 py-2">
        <div>
          {pollMode && (
            <p className="text-2xs text-[var(--warning)]">Polling mode active</p>
          )}
          {streamError && (
            <p className="text-2xs text-[var(--error)] truncate max-w-[220px]" title={streamError}>
              Stream error
            </p>
          )}
        </div>
      </div>

      {/* ── Running skill headline ── */}
      {runningGroup && (
        <div className="flex flex-wrap items-start gap-x-2 gap-y-1 border-b border-[color:color-mix(in_srgb,var(--info)_25%,white)] bg-[var(--info-light)] px-3 py-1.5">
          <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin text-[var(--info)]" aria-hidden />
          <div className="min-w-0 flex-1">
            <span className="text-xs font-medium text-[color:color-mix(in_srgb,var(--info)_70%,black)] break-words">
              {runningGroup.skillName}
            </span>
            <span className="ml-1.5 text-2xs text-[var(--info)]">running…</span>
          </div>
        </div>
      )}
      {!runningGroup && queuedGroup && (
        <div className="flex flex-wrap items-start gap-x-2 gap-y-1 border-b border-[color:color-mix(in_srgb,var(--warning)_28%,white)] bg-[var(--warning-light)] px-3 py-1.5">
          <CircleDashed className="mt-1 h-4 w-4 shrink-0 text-[var(--warning)]" aria-hidden />
          <div className="min-w-0 flex-1 space-y-0.5">
            <span className="text-xs font-medium text-[color:color-mix(in_srgb,var(--warning)_80%,black)] break-words">
              {queuedGroup.skillName}
            </span>
            <p className="text-2xs leading-snug text-[color:color-mix(in_srgb,var(--warning)_80%,black)] break-words">
              Queued — waiting for an execution worker to pick up this run.
            </p>
          </div>
        </div>
      )}

      {/* ── Tabs ── */}
      <div
        className="flex gap-0 border-b border-[var(--surface-border)]"
        role="tablist"
        aria-label="Activity panel sections"
      >
        {(["activity", "artifacts", "context", "governance"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            id={`tool-feed-tab-${tab}`}
            aria-selected={activeTab === tab}
            aria-controls={`tool-feed-panel-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => setActiveTab(tab)}
            className={`flex min-h-11 flex-1 items-center justify-center gap-1 px-1 py-2 text-xs font-medium capitalize transition-colors ${
              activeTab === tab
                ? "border-b-2 border-[var(--primary-900)] text-[var(--text-default)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-default)]"
            }`}
          >
            {tab}
            {tab === "artifacts" && hasArtifactDownloads && (
              <span className="inline-flex min-h-5 min-w-5 items-center justify-center rounded-full bg-[var(--success)] px-1 text-2xs leading-none text-white">
                {readyDownloads.length > 0 ? readyDownloads.length : "•"}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Body ── */}
      <div
        className="flex-1 overflow-auto p-3 text-xs"
        role="tabpanel"
        id={`tool-feed-panel-${activeTab}`}
        aria-labelledby={`tool-feed-tab-${activeTab}`}
      >
        {/* Activity */}
        {activeTab === "activity" && (
          <>
            {checklist.tasks.length > 0 ? (
              <div className="mb-2">
                <TodoChecklist checklist={checklist} onTaskAction={onTaskAction} />
              </div>
            ) : null}
            {(latestRecovery || heartbeatSeen) ? (
              <div className="mb-2 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] p-2 text-2xs text-[var(--text-muted)]">
                {latestRecovery ? (
                  <p>
                    Recovery mode: <strong>{latestRecovery.mode}</strong>
                    {typeof latestRecovery.attempt === "number" ? ` (attempt ${latestRecovery.attempt})` : ""}
                  </p>
                ) : null}
                {heartbeatSeen ? <p>Heartbeat events detected: run appears active.</p> : null}
              </div>
            ) : null}
            {showAgentGraph ? (
              <div className="mb-2">
                <AgentStatusGraph events={events} />
              </div>
            ) : null}
            {skillGroups.length === 0 ? (
              <p className="text-[var(--primary-400)]">
                Agent activity will appear here as skills execute.
              </p>
            ) : (
              <div className="space-y-2">
                {skillGroups.map((group) => (
                  <div
                    key={group.key}
                    className="overflow-hidden rounded border border-[var(--surface-border)]"
                  >
                    {/* Group header */}
                    <div className="flex flex-wrap items-center justify-between gap-2 bg-[var(--surface-muted)] px-2 py-1.5">
                      <span className="min-w-0 flex-1 break-words font-medium text-[var(--text-default)]">
                        {group.skillName}
                      </span>
                      <StatusBadge status={group.status} />
                    </div>
                    {/* Tool rows */}
                    {group.tools.length > 0 && (
                      <ul className="divide-y divide-[var(--surface-border)]">
                        {group.tools.map((tool, tIdx) => (
                          <li key={`${group.key}-tool-${tIdx}`} className="flex gap-2 px-3 py-1.5">
                            <span className="sr-only">{tool.status}</span>
                            <ToolStatusIcon status={tool.status} />
                            <div className="min-w-0 flex-1 space-y-0.5">
                              <span className="break-all mono text-xs text-[var(--text-muted)]">
                                {tool.name}
                              </span>
                              {tool.summary ? (
                                <p className="break-words text-2xs leading-snug text-[var(--primary-600)]">
                                  {tool.summary}
                                </p>
                              ) : null}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Artifacts */}
        {activeTab === "artifacts" && (
          <div className="space-y-3">
            {!hasArtifactDownloads ? (
              <div className="alert alert--warning text-xs">
                Downloads will appear here as each artifact is produced.
              </div>
            ) : (
              <div className="alert alert--success text-xs space-y-1.5">
                <p>
                  {readyDownloads.length > 0
                    ? `${readyDownloads.length} deliverable file${readyDownloads.length > 1 ? "s" : ""} ready.`
                    : "Report downloads are available below."}
                </p>
                {readyDownloadFilenames.length > 0 ? (
                  <ul className="list-disc space-y-0.5 pl-4 text-2xs leading-snug text-[color:color-mix(in_srgb,var(--success)_75%,black)]">
                    {readyDownloadFilenames.map((n) => (
                      <li key={n} className="break-words [overflow-wrap:anywhere]">
                        {n}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            )}
            {/* Download buttons injected from RunStudio */}
            {downloadsContent ? (
              <div className="pt-1">{downloadsContent}</div>
            ) : readyDownloads.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {readyDownloads.map((d: string) => (
                  <span
                    key={d}
                    className="max-w-full break-words rounded border border-[color:color-mix(in_srgb,var(--success)_28%,white)] bg-[var(--success-light)] px-2 py-1 text-xs font-medium text-[color:color-mix(in_srgb,var(--success)_80%,black)] [overflow-wrap:anywhere]"
                  >
                    {outputFilenames[d] && String(outputFilenames[d]).trim()
                      ? outputFilenames[d]
                      : d.toUpperCase().replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        )}

        {/* Context */}
        {activeTab === "context" && (
          <div className="space-y-3">
            {lpSnippets.length > 0 ? (
              <div>
                <p className="mb-1 font-semibold text-[var(--text-muted)]">
                  Leading-practice snippets
                </p>
                <div className="space-y-1.5">
                  {lpSnippets.map((snippet, idx) => (
                    <pre
                      key={`lp-${idx}`}
                      className="max-h-20 overflow-auto whitespace-pre-wrap rounded bg-[var(--primary-100)] p-1.5 text-2xs leading-relaxed text-[var(--text-muted)]"
                    >
                      {snippet}
                    </pre>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-[var(--primary-400)]">No LP snippets retrieved yet.</p>
            )}

            {Array.isArray(memorySummary?.non_negotiables) &&
              memorySummary!.non_negotiables!.length > 0 && (
                <div>
                  <p className="mb-1 font-semibold text-[var(--text-muted)]">Non-negotiables</p>
                  <ul className="list-disc space-y-0.5 pl-4 text-xs text-[var(--text-muted)]">
                    {memorySummary!.non_negotiables!.slice(0, 6).map((nn, idx) => (
                      <li key={idx}>{nn}</li>
                    ))}
                  </ul>
                </div>
              )}

            {Array.isArray(memorySummary?.recent_changes) &&
              memorySummary!.recent_changes!.length > 0 && (
                <div>
                  <p className="mb-1 font-semibold text-[var(--text-muted)]">Recent changes</p>
                  <ul className="space-y-1">
                    {memorySummary!.recent_changes!.slice(0, 4).map((c, idx) => (
                      <li
                        key={idx}
                        className="rounded bg-[var(--surface-muted)] px-2 py-1 text-2xs text-[var(--text-muted)]"
                      >
                        {c.payload?.summary ?? c.event_type ?? "—"}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

            {lpSnippets.length === 0 &&
              !memorySummary?.non_negotiables?.length &&
              !memorySummary?.recent_changes?.length && (
                <p className="text-[var(--primary-400)]">
                  Context will populate once the run starts.
                </p>
              )}
          </div>
        )}

        {/* Governance */}
        {activeTab === "governance" && (
          <div className="space-y-3">
            <div className="rounded border border-[var(--surface-border)] p-2">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold text-[var(--text-default)]">Permission simulation</p>
                <button
                  type="button"
                  className="min-h-9 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-3 py-2 text-2xs"
                  disabled={!permissionPanel || permissionPanel.busy}
                  onClick={permissionPanel?.onSimulate}
                >
                  {permissionPanel?.busy ? "Running…" : "Simulate"}
                </button>
              </div>
              {permissionPanel?.result?.stages && Array.isArray(permissionPanel.result.stages) ? (
                <div className="max-h-32 overflow-auto text-2xs">
                  {(permissionPanel.result.stages as Array<any>).map((st, idx) => (
                    <div key={`perm-${idx}`} className="border-t border-[var(--surface-border)] py-1">
                      <strong>{String(st.stage || "stage")}</strong> — {st.allowed ? "allow" : "deny"} ({String(st.code || "n/a")})
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-2xs text-[var(--text-muted)]">Run simulation to view stage-by-stage policy decisions.</p>
              )}
            </div>

            <div className="rounded border border-[var(--surface-border)] p-2">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold text-[var(--text-default)]">Hook governance</p>
                <button
                  type="button"
                  className="min-h-9 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-3 py-2 text-2xs"
                  disabled={!hooksPanel || hooksPanel.loading}
                  onClick={hooksPanel?.onRefresh}
                >
                  {hooksPanel?.loading ? "Loading…" : "Refresh"}
                </button>
              </div>
              {hooksPanel?.hooks?.length ? (
                <div className="max-h-40 space-y-1 overflow-auto text-2xs">
                  {hooksPanel.hooks.map((h, idx) => {
                    const hookName = String(h.hook_name || "");
                    return (
                      <div key={`hook-${idx}`} className="rounded border border-[var(--surface-border)] p-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium break-all">{hookName}</span>
                          <span>{h.disabled ? "disabled" : "enabled"}</span>
                        </div>
                        <p className="text-[var(--text-muted)]">
                          point={String(h.hook_point || "n/a")} source={String(h.source || "n/a")} order={String(h.order || "n/a")}
                        </p>
                        <div className="mt-1 flex gap-1">
                          <input
                            value={disableReason}
                            onChange={(e) => setDisableReason(e.target.value)}
                            className="min-h-9 w-full rounded border border-[var(--surface-border)] px-2 py-1.5 text-2xs"
                            placeholder="Disable reason"
                          />
                          <button
                            type="button"
                            className="min-h-9 shrink-0 rounded border border-[var(--surface-border)] bg-[var(--warning-light)] px-3 py-2 text-2xs"
                            onClick={() => hooksPanel.onDisable(hookName, disableReason)}
                          >
                            Disable
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-2xs text-[var(--text-muted)]">No hooks loaded yet.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
