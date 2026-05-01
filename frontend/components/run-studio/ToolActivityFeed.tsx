"use client";

import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AgentStatusGraph } from "@/components/run-studio/AgentStatusGraph";
import { TodoChecklist } from "@/components/run-studio/TodoChecklist";
import { Button } from "@/components/ui/Button";
import { DeckCanvas, DeckTabPanel } from "@/components/deck-canvas";
import { DocumentCanvas, DOCUMENT_CANVAS_ENABLED } from "@/components/run-studio/DocumentCanvas";
import { useTodoChecklistState } from "@/hooks/useTodoChecklistState";
import {
  toolCallsFromAgentRoundPayload,
  type ToolCallPreview,
} from "@/lib/agentToolRound";
import type { ParsedRunEvent } from "@/lib/runEvents";
import type { RunTodoRow } from "@/lib/runTodosFromEvents";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToolCall = {
  name: string;
  status: "running" | "done" | "failed";
  summary: string;
  preview?: ToolCallPreview;
};

const DECK_CANVAS_ENABLED = process.env.NEXT_PUBLIC_DECK_CANVAS_ENABLED !== "false";

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
          skillName: "Digital Teammate",
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
            preview: row.preview,
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

function ToolPreview({ preview }: { preview: ToolCallPreview }) {
  if (preview.kind === "web_capture") {
    const hostname = (() => {
      if (!preview.url) return "";
      try {
        return new URL(preview.url).hostname;
      } catch {
        return preview.url;
      }
    })();
    return (
      <div
        className="mt-1 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-2 py-1.5"
        role="group"
        aria-label="Web capture preview"
      >
        <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
          <span>Web capture</span>
          {preview.ok === false ? (
            <span className="text-[var(--error)]">· error</span>
          ) : preview.truncated ? (
            <span>· truncated</span>
          ) : null}
        </div>
        {preview.title ? (
          <p className="break-words text-2xs font-medium leading-snug text-[var(--text-default)]">
            {preview.title}
          </p>
        ) : null}
        {preview.url ? (
          <a
            href={preview.url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all text-[11px] leading-snug text-[var(--info)] underline-offset-2 hover:underline"
            title={preview.url}
          >
            {hostname || preview.url}
          </a>
        ) : null}
        {preview.snippet ? (
          <p className="mt-1 break-words text-2xs leading-snug text-[var(--primary-600)]">
            {preview.snippet}
          </p>
        ) : null}
        {preview.error ? (
          <p className="mt-1 break-words text-2xs leading-snug text-[var(--error)]">
            {preview.error}
          </p>
        ) : null}
      </div>
    );
  }
  return null;
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
  onRegenerateSlide,
  slideRegenerateBusyIndex,
  downloadsContent,
  showAgentGraph = true,
  hooksPanel,
  permissionPanel,
  projectId,
  runId,
  agreedDecisions,
}: {
  events: string[];
  parsedEvents?: ParsedRunEvent[];
  runChecklistTodos?: RunTodoRow[];
  artifacts: any;
  pollMode: boolean;
  streamError: string | null;
  showAgentGraph?: boolean;
  projectId?: string;
  runId?: string;
  /** Render slot for download buttons — passed from the parent with full artifact access */
  downloadsContent?: React.ReactNode;
  onTaskAction?: (taskId: string, action: "retry" | "skip" | "approve") => void;
  onRegenerateSlide?: (slideIndex: number, instruction?: string, elementPath?: string) => void;
  slideRegenerateBusyIndex?: number | null;
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
  /** Slide decisions agreed during collaborative building */
  agreedDecisions?: Array<{
    slide_num: number;
    title: string;
    key_message?: string;
    slide_type?: string;
    agreed?: boolean;
  }>;
}) {
  const [activeTab, setActiveTab] = useState<"activity" | "artifacts" | "deck" | "context" | "governance" | "canvas" | "decisions">(
    "activity"
  );
  const [disableReason, setDisableReason] = useState("");
  const [slideModalOpen, setSlideModalOpen] = useState(false);
  const [selectedSlideIndex, setSelectedSlideIndex] = useState<number | null>(null);
  const [selectedSlideTitle, setSelectedSlideTitle] = useState("");
  const [slideInstruction, setSlideInstruction] = useState("");
  const [selectedElementPath, setSelectedElementPath] = useState<string>("");

  const skillGroups = useMemo(() => buildSkillGroups(events), [events]);
  const checklist = useTodoChecklistState({
    parsedEvents: parsedEvents ?? [],
    snapshotRows: runChecklistTodos ?? [],
  });

  const readyDownloads: string[] = useMemo(
    () =>
      Array.isArray(artifacts?.ready_downloads)
        ? artifacts.ready_downloads.map((x: unknown) => String(x))
        : [],
    [artifacts?.ready_downloads]
  );

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
  const hasCanvasContent =
    DOCUMENT_CANVAS_ENABLED &&
    ["narrative_md", "sop_markdown", "raci_markdown", "process_map_mermaid"].some(
      (k) => typeof artifacts?.[k] === "string" && (artifacts[k] as string).length > 0
    );
  const pptxSlides = useMemo(
    () => (Array.isArray(artifacts?.pptx_slides) ? artifacts.pptx_slides : []),
    [artifacts?.pptx_slides]
  );

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

  const openSlideRegenerateModal = useCallback((slideIndex: number, slideTitle: string) => {
    setSelectedSlideIndex(slideIndex);
    setSelectedSlideTitle(slideTitle);
    setSlideInstruction(
      `Regenerate slide ${slideIndex} (${slideTitle}) to improve clarity, layout, and content quality while preserving slide intent.`
    );
    setSelectedElementPath("");
    setSlideModalOpen(true);
  }, []);

  const closeSlideRegenerateModal = useCallback(() => {
    if (slideRegenerateBusyIndex !== null) return;
    setSlideModalOpen(false);
    setSelectedSlideIndex(null);
    setSelectedSlideTitle("");
    setSlideInstruction("");
    setSelectedElementPath("");
  }, [slideRegenerateBusyIndex]);

  const submitSlideRegeneration = useCallback(() => {
    if (!onRegenerateSlide || selectedSlideIndex === null) return;
    const instruction = slideInstruction.trim();
    if (!instruction) return;
    onRegenerateSlide(selectedSlideIndex, instruction, selectedElementPath || undefined);
    setSlideModalOpen(false);
  }, [onRegenerateSlide, selectedElementPath, selectedSlideIndex, slideInstruction]);

  const onCanvasElementClick = useCallback(
    ({ slideIndex, elementPath }: { slideIndex: number; elementPath: string }) => {
      const slide = pptxSlides.find((s: any, i: number) => {
        const idx = Number(s?.slide_index) > 0 ? Number(s.slide_index) : i + 1;
        return idx === slideIndex;
      });
      const slideTitle = String(slide?.title || `Slide ${slideIndex}`).trim();
      setSelectedSlideIndex(slideIndex);
      setSelectedSlideTitle(slideTitle);
      setSelectedElementPath(elementPath);
      setSlideInstruction(
        `Update only ${elementPath} on slide ${slideIndex} (${slideTitle}). Preserve all other content and layout on this slide and all other slides.`
      );
      setSlideModalOpen(true);
    },
    [pptxSlides]
  );

  useEffect(() => {
    if (!slideModalOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSlideRegenerateModal();
        return;
      }
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (!slideInstruction.trim() || slideRegenerateBusyIndex !== null) return;
        submitSlideRegeneration();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    closeSlideRegenerateModal,
    slideInstruction,
    slideModalOpen,
    slideRegenerateBusyIndex,
    submitSlideRegeneration,
  ]);

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
        {(["activity", "artifacts", "canvas", "deck", "context", "decisions", "governance"] as const).filter(
          (tab) => tab !== "canvas" || DOCUMENT_CANVAS_ENABLED
        ).map((tab) => (
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
            {tab === "canvas" && hasCanvasContent && (
              <span className="inline-flex min-h-5 min-w-5 items-center justify-center rounded-full bg-[var(--primary-900)] px-1 text-2xs leading-none text-white">
                •
              </span>
            )}
            {tab === "deck" && pptxSlides.length > 0 && (
              <span className="inline-flex min-h-5 min-w-5 items-center justify-center rounded-full bg-[var(--info)] px-1 text-2xs leading-none text-white">
                {pptxSlides.length}
              </span>
            )}
            {tab === "decisions" && agreedDecisions && agreedDecisions.length > 0 && (
              <span className="inline-flex min-h-5 min-w-5 items-center justify-center rounded-full bg-[var(--primary-600)] px-1 text-2xs leading-none text-white">
                {agreedDecisions.length}
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
                              {tool.preview ? (
                                <ToolPreview preview={tool.preview} />
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
            {pptxSlides.length > 0 ? (
              <div className="space-y-2 rounded border border-[var(--surface-border)] p-2">
                <p className="text-xs font-semibold text-[var(--text-default)]">Slide actions</p>
                <div className="space-y-1.5">
                  {pptxSlides.map((slide: any, idx: number) => {
                    const slideIndex = Number(slide?.slide_index) > 0 ? Number(slide.slide_index) : idx + 1;
                    const slideTitle = String(slide?.title || `Slide ${slideIndex}`).trim();
                    const busy = slideRegenerateBusyIndex === slideIndex;
                    return (
                      <div
                        key={`slide-action-${slideIndex}`}
                        className="flex items-center justify-between gap-2 rounded border border-[var(--surface-border)] px-2 py-1.5"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-2xs font-medium text-[var(--text-default)]">
                            {slideIndex}. {slideTitle}
                          </p>
                          <p className="text-2xs text-[var(--text-muted)]">
                            {String(slide?.slide_type || "slide")}
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="secondary"
                          className="min-h-9 shrink-0 px-2 py-1 text-2xs"
                          disabled={Boolean(busy) || !onRegenerateSlide}
                          onClick={() => openSlideRegenerateModal(slideIndex, slideTitle)}
                        >
                          {busy ? "Queuing..." : "Regenerate slide"}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
            {DECK_CANVAS_ENABLED && pptxSlides.length > 0 ? (
              <div className="space-y-2 rounded border border-[var(--surface-border)] p-2">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-[var(--text-default)]">Canvas preview</p>
                  <button
                    type="button"
                    className="text-2xs text-[var(--accent-blue)] hover:underline"
                    onClick={() => setActiveTab("deck")}
                  >
                    Open Deck tab →
                  </button>
                </div>
                <p className="text-2xs text-[var(--text-muted)]">
                  Click an element to prefill a targeted update prompt.
                </p>
                <DeckCanvas slides={pptxSlides} className="max-h-[360px] overflow-auto space-y-2" onElementClick={onCanvasElementClick} />
              </div>
            ) : null}
          </div>
        )}

        {/* Canvas */}
        {activeTab === "canvas" && DOCUMENT_CANVAS_ENABLED && (
          <div className="-m-3 flex h-full min-h-[400px] flex-col">
            <DocumentCanvas
              artifacts={artifacts}
              projectId={projectId ?? ""}
              runId={runId ?? ""}
            />
          </div>
        )}

        {/* Deck */}
        {activeTab === "deck" && (
          <div className="h-full min-h-0">
            {pptxSlides.length === 0 ? (
              <p className="text-[var(--primary-400)]">
                Deck preview becomes available after the PPTX slide JSON is generated.
              </p>
            ) : (
              <DeckTabPanel
                slides={pptxSlides}
                onElementClick={onCanvasElementClick}
                slideRegenerateBusyIndex={slideRegenerateBusyIndex ?? null}
                className="flex h-full min-h-0 flex-col gap-3 md:flex-row"
              />
            )}
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

        {/* Decisions — agreed collaborative slide structure */}
        {activeTab === "decisions" && (
          <div className="space-y-2">
            {agreedDecisions && agreedDecisions.length > 0 ? (
              <>
                <p className="text-2xs font-medium text-[var(--text-muted)]">
                  {agreedDecisions.length} slide{agreedDecisions.length !== 1 ? "s" : ""} agreed
                </p>
                <ol className="space-y-1.5">
                  {agreedDecisions.map((d, idx) => (
                    <li
                      key={`decision-${idx}-${d.slide_num}`}
                      className="flex items-start gap-2 rounded border border-[var(--surface-border)] bg-white p-2"
                    >
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--primary-600)] text-2xs font-bold text-white">
                        {d.slide_num}
                      </span>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-[var(--text-default)]">{d.title}</p>
                        {d.key_message && (
                          <p className="mt-0.5 text-2xs text-[var(--text-muted)]">{d.key_message}</p>
                        )}
                        {d.slide_type && (
                          <span className="mt-0.5 inline-block rounded bg-[var(--surface-muted)] px-1 py-0.5 text-2xs text-[var(--text-subtle)]">
                            {d.slide_type}
                          </span>
                        )}
                      </div>
                      {d.agreed && (
                        <span className="ml-auto shrink-0 text-xs text-[var(--success)]">✓</span>
                      )}
                    </li>
                  ))}
                </ol>
              </>
            ) : (
              <p className="text-2xs text-[var(--text-muted)]">
                No slides agreed yet. Start a conversation with Sheldon to build the deck structure collaboratively.
              </p>
            )}
          </div>
        )}
      </div>
      {slideModalOpen && selectedSlideIndex !== null ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-xl rounded-lg border border-[var(--surface-border)] bg-white p-4 shadow-lg">
            <h3 className="text-sm font-semibold text-[var(--text-default)]">
              Regenerate slide {selectedSlideIndex}
            </h3>
            <p className="mt-1 text-2xs text-[var(--text-muted)]">
              {selectedSlideTitle}
            </p>
            {selectedElementPath ? (
              <p className="mt-1 text-2xs text-[var(--text-muted)]">
                Target element path: <span className="mono">{selectedElementPath}</span>
              </p>
            ) : null}
            <p className="mt-1 text-2xs text-[var(--text-muted)]">
              Press <kbd>Esc</kbd> to cancel, <kbd>Cmd/Ctrl+Enter</kbd> to queue.
            </p>
            <label className="mt-3 block text-2xs font-medium text-[var(--text-default)]">
              Instruction
            </label>
            <textarea
              value={slideInstruction}
              onChange={(e) => setSlideInstruction(e.target.value)}
              rows={5}
              className="mt-1 w-full rounded border border-[var(--surface-border)] px-2 py-2 text-xs"
              placeholder="Describe the changes you want on this slide"
            />
            <div className="mt-3 flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={closeSlideRegenerateModal}
                disabled={slideRegenerateBusyIndex !== null}
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={submitSlideRegeneration}
                disabled={!slideInstruction.trim() || slideRegenerateBusyIndex !== null}
              >
                {slideRegenerateBusyIndex === selectedSlideIndex ? "Queuing..." : "Queue regeneration"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
