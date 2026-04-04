"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AgentStatusGraph } from "@/components/run-studio/AgentStatusGraph";
import { toolCallsFromAgentRoundPayload } from "@/lib/agentToolRound";
import { extractRunTodoRowsFromEventData, mergeRunEventEnvelope } from "@/lib/runTodosFromEvents";

type ParsedEvent = {
  raw: string;
  eventType: string;
  payloadText: string;
  payloadObj: Record<string, unknown> | null;
  category: "errors" | "decisions" | "outputs" | "live";
  severity: "info" | "warning" | "error" | "success";
  title: string;
  summary: string;
};

function parsePayload(payloadText: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(payloadText);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function humanizeEvent(
  eventType: string,
  payloadObj: Record<string, unknown> | null
): Omit<ParsedEvent, "raw" | "eventType" | "payloadText" | "payloadObj"> {
  const ctx =
    payloadObj && typeof payloadObj === "object"
      ? mergeRunEventEnvelope(payloadObj)
      : ({} as Record<string, unknown>);
  const status = typeof ctx.status === "string" ? ctx.status : "";
  const lowered = `${eventType} ${status}`.toLowerCase();

  if (lowered.includes("failed") || lowered.includes("error")) {
    return {
      category: "errors",
      severity: "error",
      title: "Issue detected",
      summary: "The run encountered an error and may need attention.",
    };
  }
  if (lowered.includes("warn") || lowered.includes("throttle")) {
    return {
      category: "errors",
      severity: "warning",
      title: "Warning",
      summary: "The system reported a warning. Review details before proceeding.",
    };
  }
  if (eventType === "done") {
    return {
      category: "outputs",
      severity: "success",
      title: "Run completed",
      summary: "Deliverable generation has completed.",
    };
  }
  if (eventType === "plan_ready" || status === "awaiting_hitl_approval" || lowered.includes("approve")) {
    return {
      category: "decisions",
      severity: "info",
      title: "Approval checkpoint",
      summary: "The run is waiting for user approval before execution.",
    };
  }
  if (eventType === "plan_blocked") {
    return {
      category: "decisions",
      severity: "warning",
      title: "Plan blocked",
      summary: "Automated permission/governance checks blocked execution before approval.",
    };
  }
  if (eventType === "permission_stage") {
    const stage = typeof ctx.stage === "string" ? ctx.stage : "permission_stage";
    const allowed = ctx.allowed === true;
    return {
      category: "decisions",
      severity: allowed ? "info" : "warning",
      title: `Permission: ${stage}`,
      summary: allowed ? "Stage passed." : "Stage failed. Review code/reason in details.",
    };
  }
  if (eventType === "hook_result") {
    const outcome = String(ctx.outcome ?? "unknown").toUpperCase();
    return {
      category: outcome === "WARN" || outcome === "ABORT" ? "errors" : "live",
      severity: outcome === "WARN" ? "warning" : outcome === "ABORT" ? "error" : "info",
      title: `Hook: ${String(ctx.hook_name ?? "unknown")}`,
      summary: `Outcome: ${outcome}.`,
    };
  }
  if (eventType === "run_control_applied") {
    return {
      category: "decisions",
      severity: "warning",
      title: "Run control applied",
      summary: "A pause/resume/abort control action was applied at a checkpoint.",
    };
  }
  if (eventType === "recovery_mode") {
    return {
      category: "live",
      severity: "warning",
      title: "Recovery mode",
      summary: "The worker switched into a retry/recovery mode.",
    };
  }
  if (eventType === "heartbeat") {
    return {
      category: "live",
      severity: "info",
      title: "Heartbeat",
      summary: "Long-running execution heartbeat received.",
    };
  }
  if (eventType === "deliverable_quality") {
    const it = typeof ctx.iteration === "number" ? ctx.iteration : "?";
    const passed = ctx.passed === true;
    return {
      category: "outputs",
      severity: passed ? "success" : "warning",
      title: `Deliverable quality (round ${it})`,
      summary: passed
        ? "Contract-based quality gate passed."
        : "Scores fell below the registered contract threshold; remediation may run.",
    };
  }
  if (status === "execution_enqueued" || lowered.includes("enqueued")) {
    return {
      category: "live",
      severity: "info",
      title: "Queued for execution",
      summary: "The run is approved and queued. It will start when a worker picks it up.",
    };
  }
  if (eventType === "agent_tool_round") {
    const agent = String(
      ctx.skill_name ?? ctx.agent ?? ctx.output_type ?? "sub-agent"
    );
    const rows = toolCallsFromAgentRoundPayload(ctx);
    const roundLabel =
      typeof ctx.round === "number" ? `Round ${ctx.round}` : "";
    if (rows.length === 0) {
      return {
        category: "live",
        severity: "info",
        title: roundLabel ? `Agent tool round — ${roundLabel}` : "Agent tool round",
        summary: `${agent} invoked tools; names were not included in this event.`,
      };
    }
    const names = rows.map((r) => r.name).join(", ");
    const meta = rows
      .filter((r) => r.summary)
      .map((r) => `${r.name}: ${r.summary}`)
      .join(" · ");
    const summaryBody = meta || `${agent} · ${rows.length} tool call(s)`;
    return {
      category: "live",
      severity: "info",
      title: names,
      summary: roundLabel ? `${summaryBody} · ${roundLabel}` : summaryBody,
    };
  }
  if (eventType === "coordinator_plan" || eventType === "execution_plan") {
    return {
      category: "decisions",
      severity: "info",
      title: "Coordinator plan",
      summary: "The coordinator produced an execution plan and rationale for this run.",
    };
  }
  if (eventType === "run_todo_snapshot" && payloadObj) {
    const rows = extractRunTodoRowsFromEventData(payloadObj);
    const n = rows.length;
    return {
      category: "live",
      severity: "info",
      title: "Run checklist updated",
      summary:
        n > 0
          ? `${n} step(s) on the run checklist were refreshed. See Run checklist above the stream.`
          : "Run checklist snapshot received.",
    };
  }
  if (eventType === "visual_qa_report" && payloadObj) {
    const st = String(ctx.status ?? "").toLowerCase() || "unknown";
    const sev =
      st === "fail" ? "error" : st === "warn" ? "warning" : st === "pass" ? "success" : "info";
    const cat = st === "fail" ? "errors" : "live";
    return {
      category: cat,
      severity: sev,
      title: `Visual QA: ${st}`,
      summary: "Full findings and status are in the Instruction chat (left). Reply there to iterate with the AI.",
    };
  }
  if (eventType === "evaluator_retry_requested" && payloadObj) {
    const excerptRaw = ctx.findings_excerpt;
    const excerpt =
      Array.isArray(excerptRaw) ? excerptRaw.filter((x): x is string => typeof x === "string") : [];
    const vsum =
      typeof ctx.visual_qa_summary === "string" ? ctx.visual_qa_summary.trim() : "";
    const ridx = ctx.retry_index;
    const maxR = ctx.max_remediation_rounds;
    const attempt =
      typeof ridx === "number"
        ? typeof maxR === "number"
          ? `Attempt ${ridx}/${maxR}`
          : `Attempt ${ridx}`
        : "Remediation";
    return {
      category: "live",
      severity: "warning",
      title: "Visual QA remediation re-run",
      summary:
        excerpt.slice(0, 4).join(" · ") ||
        vsum ||
        `${attempt}: regenerating outputs that failed the pre-review evaluator.`,
    };
  }
  if (eventType === "qa_report" || lowered.includes("guardrail")) {
    return {
      category: "decisions",
      severity: "info",
      title: "Quality and compliance review",
      summary: "Quality and guardrail checks were evaluated for this run.",
    };
  }
  if (eventType === "output_chunk" || lowered.includes("artifact") || lowered.includes("output")) {
    return {
      category: "outputs",
      severity: "success",
      title: "Output generated",
      summary: "A deliverable output update is available.",
    };
  }
  return {
    category: "live",
    severity: "info",
    title: "Execution update",
    summary: "The system posted a progress update.",
  };
}

function CoordinatorPlanEventBody({ payload }: { payload: Record<string, unknown> }) {
  const plannedRaw = payload.planned_outputs;
  const planned =
    Array.isArray(plannedRaw) && plannedRaw.every((x) => typeof x === "string")
      ? (plannedRaw as string[])
      : [];
  const thinking =
    typeof payload.thinking_excerpt === "string" && payload.thinking_excerpt.trim()
      ? payload.thinking_excerpt.trim()
      : null;
  const fallbackReason =
    typeof payload.fallback_reason === "string" && payload.fallback_reason.trim()
      ? payload.fallback_reason.trim()
      : null;
  const usedLlm = payload.used_llm_plan === true;
  const runContract = payload.run_contract_present === true;

  const notes = payload.per_output_notes;
  const noteEntries =
    notes && typeof notes === "object" && !Array.isArray(notes)
      ? Object.entries(notes as Record<string, unknown>).filter(([k]) => k.trim())
      : [];

  return (
    <>
      {planned.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {planned.map((p) => (
            <span
              key={p}
              className="rounded bg-[var(--surface-muted)] px-2 py-0.5 text-2xs font-medium text-[var(--text-muted)]"
            >
              {p}
            </span>
          ))}
        </div>
      ) : null}
      <p className="mt-1.5 text-2xs leading-snug text-[var(--primary-600)]">
        LLM plan: {usedLlm ? "yes" : "no"}
        {fallbackReason ? ` · ${fallbackReason}` : ""}
        {runContract ? " · run contract active" : ""}
      </p>
      {thinking ? (
        <div className="mt-2 overflow-hidden rounded-lg border border-[color:color-mix(in_srgb,var(--info)_28%,white)] bg-[var(--info-light)]">
          {/* Header */}
          <div className="flex items-center gap-2 border-b border-[color:color-mix(in_srgb,var(--info)_18%,white)] px-3 py-1.5">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[color:color-mix(in_srgb,var(--accent-blue-light)_35%,white)]">
              <svg className="h-2.5 w-2.5 text-[var(--accent-indigo)]" viewBox="0 0 20 20" fill="currentColor">
                <path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.298.064-.588.143-.868a4 4 0 10-4.286 0c.079.28.128.57.143.868h4z" />
              </svg>
            </span>
            <span className="text-xs font-semibold text-[var(--accent-indigo)]">Coordinator reasoning</span>
            <span className="ml-auto text-2xs text-[var(--accent-blue-light)]">extended thinking</span>
          </div>
          {/* Body — scrollable, always visible */}
          <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words border-l-2 border-[color:color-mix(in_srgb,var(--accent-indigo)_45%,white)] px-3 py-2 font-sans text-xs leading-relaxed text-[var(--text-default)]">
            {thinking}
          </pre>
        </div>
      ) : fallbackReason && !usedLlm ? (
        <p className="mt-2 rounded border border-[color:color-mix(in_srgb,var(--warning)_32%,white)] bg-[var(--warning-light)] px-2 py-1.5 text-xs text-[color:color-mix(in_srgb,var(--warning)_85%,black)]">
          {fallbackReason}
        </p>
      ) : null}
      {noteEntries.length > 0 ? (
        <details className="mt-2 rounded border border-[var(--surface-border)] bg-white">
          <summary className="cursor-pointer select-none px-2 py-1.5 text-xs text-[var(--text-muted)]">
            Per-output notes ({noteEntries.length})
          </summary>
          <ul className="max-h-32 space-y-1 overflow-y-auto px-2 pb-2 text-xs text-[var(--text-muted)]">
            {noteEntries.slice(0, 12).map(([k, v]) => (
              <li key={k}>
                <span className="font-medium text-[var(--text-default)]">{k}:</span> {String(v)}
              </li>
            ))}
            {noteEntries.length > 12 ? (
              <li className="text-[var(--primary-600)]">+{noteEntries.length - 12} more…</li>
            ) : null}
          </ul>
        </details>
      ) : null}
    </>
  );
}

function isCoordinatorPlanEvent(eventType: string): boolean {
  return eventType === "coordinator_plan" || eventType === "execution_plan";
}

export function ZoneCLiveMonitor({
  events,
  evaluatorSummary,
  runControls,
  showAgentGraph = true,
}: {
  events: string[];
  evaluatorSummary?: {
    qaPassed?: boolean;
    visualQaPassed?: boolean;
    guardrailsPassed?: boolean;
    status?: string;
  } | null;
  runControls?: {
    canPause: boolean;
    canResume: boolean;
    canStop: boolean;
    busy: boolean;
    onPause: () => void;
    onResume: () => void;
    onStop: () => void;
  };
  showAgentGraph?: boolean;
}) {
  const [activeTab, setActiveTab] = useState<"live" | "errors" | "decisions" | "outputs">("live");
  const [compactTrail, setCompactTrail] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll event list when new events arrive on the active tab
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events, activeTab]);

  const parsedEvents = useMemo<ParsedEvent[]>(() => {
    return events.map((line) => {
      const sep = line.indexOf(":");
      const eventType = (sep >= 0 ? line.slice(0, sep) : "step").trim();
      const payloadText = (sep >= 0 ? line.slice(sep + 1) : line).trim();
      const payloadObj = parsePayload(payloadText);
      const human = humanizeEvent(eventType, payloadObj);
      return {
        raw: line,
        eventType,
        payloadText,
        payloadObj,
        ...human,
      };
    });
  }, [events]);

  const buckets = useMemo(() => {
    const errors = parsedEvents.filter((e) => e.category === "errors");
    const decisions = parsedEvents.filter((e) => e.category === "decisions");
    const outputs = parsedEvents.filter((e) => e.category === "outputs");
    return { live: parsedEvents, errors, decisions, outputs };
  }, [parsedEvents]);

  const tabItems: Array<{ id: "live" | "errors" | "decisions" | "outputs"; label: string; count: number }> = [
    { id: "live", label: "Live Events", count: buckets.live.length },
    { id: "errors", label: "Errors/Warnings", count: buckets.errors.length },
    { id: "decisions", label: "Decisions", count: buckets.decisions.length },
    { id: "outputs", label: "Outputs", count: buckets.outputs.length },
  ];
  const current = buckets[activeTab];

  return (
    <div className="max-h-[75vh] overflow-y-auto rounded-lg border border-[var(--surface-border)] bg-white p-4">
      <h3 className="text-lg font-semibold">Execution Audit Trail</h3>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Plain-language timeline of what the system did, what decisions were made, and whether outputs are ready.
      </p>
      {evaluatorSummary ? (
        <div className="surface-muted mt-2 grid gap-1 rounded p-2 text-xs sm:grid-cols-4">
          <p>QA: {evaluatorSummary.qaPassed ? "pass" : "fail"}</p>
          <p>Visual QA: {evaluatorSummary.visualQaPassed ? "pass" : "fail"}</p>
          <p>Guardrails: {evaluatorSummary.guardrailsPassed ? "pass" : "fail"}</p>
          <p>Pipeline: {evaluatorSummary.status ?? "unknown"}</p>
        </div>
      ) : null}
      {showAgentGraph ? (
        <div className="mt-2">
          <AgentStatusGraph events={events} />
        </div>
      ) : null}
      {runControls ? (
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Run execution controls">
          <button
            type="button"
            className="min-h-11 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-3 py-2 text-xs text-[var(--text-default)]"
            disabled={!runControls.canPause || runControls.busy}
            onClick={runControls.onPause}
          >
            Pause
          </button>
          <button
            type="button"
            className="min-h-11 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-3 py-2 text-xs text-[var(--text-default)]"
            disabled={!runControls.canResume || runControls.busy}
            onClick={runControls.onResume}
          >
            Resume
          </button>
          <button
            type="button"
            className="min-h-11 rounded border border-[color:color-mix(in_srgb,var(--error)_30%,white)] bg-[var(--error-light)] px-3 py-2 text-xs text-[var(--error)]"
            disabled={!runControls.canStop || runControls.busy}
            onClick={runControls.onStop}
          >
            Stop
          </button>
        </div>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div
          className="flex flex-wrap gap-2"
          role="tablist"
          aria-label="Audit trail filters"
        >
          {tabItems.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`zonec-tab-${tab.id}`}
              aria-selected={activeTab === tab.id}
              aria-controls={`zonec-panel-${tab.id}`}
              tabIndex={activeTab === tab.id ? 0 : -1}
              className={`min-h-11 rounded px-3 py-2 text-xs ${activeTab === tab.id ? "bg-[var(--primary-900)] text-white" : "border border-[var(--surface-border)] bg-[var(--surface-muted)] text-[var(--text-muted)]"}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label} ({tab.count})
            </button>
          ))}
        </div>
        <button
          type="button"
          className="min-h-9 rounded border border-[var(--surface-border)] bg-white px-3 py-1 text-2xs font-medium text-[var(--text-default)]"
          onClick={() => setCompactTrail((v) => !v)}
          aria-pressed={compactTrail}
        >
          {compactTrail ? "Detailed events" : "Compact events"}
        </button>
      </div>
      <div
        ref={scrollRef}
        role="tabpanel"
        id={`zonec-panel-${activeTab}`}
        aria-labelledby={`zonec-tab-${activeTab}`}
        className={`mt-2 overflow-auto rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] p-2 text-xs ${compactTrail ? "max-h-96" : "max-h-80"}`}
      >
        {current.length === 0 ? (
          <p className="text-[var(--text-muted)]">No entries in this view yet.</p>
        ) : (
          <ul className="space-y-2">
            {current.map((event, idx) => {
              const mergedPayload =
                event.payloadObj && typeof event.payloadObj === "object"
                  ? mergeRunEventEnvelope(event.payloadObj)
                  : null;
              const planPayload = mergedPayload;
              const rationale =
                isCoordinatorPlanEvent(event.eventType) &&
                planPayload &&
                typeof planPayload.rationale === "string"
                  ? planPayload.rationale.trim()
                  : "";
              const showPlanCard = isCoordinatorPlanEvent(event.eventType) && planPayload;

              return (
                <li key={`${activeTab}-${idx}`} className={`rounded border border-[var(--surface-border)] bg-white ${compactTrail ? "px-2 py-1" : "px-3 py-2"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <p className={`font-medium text-[var(--text-default)] ${compactTrail ? "text-2xs" : ""}`}>{event.title}</p>
                    <span className={`status-pill ${
                      event.severity === "error"
                        ? "status-pill--error"
                        : event.severity === "warning"
                          ? "status-pill--warning"
                          : event.severity === "success"
                            ? "status-pill--success"
                            : "status-pill--info"
                    }`}>
                      {event.severity.toUpperCase()}
                    </span>
                  </div>
                  <p className={`mt-1 text-[var(--text-muted)] ${compactTrail ? "line-clamp-2 text-2xs" : ""}`}>
                    {rationale ? rationale : event.summary}
                  </p>
                  <p className="mt-0.5 text-2xs text-[var(--text-caption)]">
                    Sequence {idx + 1} of {current.length}
                    {current.length - idx - 1 > 0 ? ` · ${current.length - idx - 1} newer` : ""}
                  </p>
                  {event.eventType === "evaluator_retry_requested" &&
                  mergedPayload &&
                  Array.isArray(mergedPayload.findings_excerpt) &&
                  mergedPayload.findings_excerpt.length > 0 ? (
                    <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[var(--text-default)]">
                      {(mergedPayload.findings_excerpt as unknown[])
                        .filter((x): x is string => typeof x === "string")
                        .map((f, fi) => (
                          <li key={fi} className="text-[11px] leading-snug">
                            {f}
                          </li>
                        ))}
                    </ul>
                  ) : null}
                  {showPlanCard ? (
                    <CoordinatorPlanEventBody payload={planPayload} />
                  ) : event.eventType === "visual_qa_report" ? null : event.payloadObj ? (
                    <div className="mt-1 rounded bg-[var(--surface-muted)] px-2 py-1 text-xs text-[var(--text-muted)]">
                      {typeof event.payloadObj.schema_version !== "string" ? (
                        <p className="mb-1 text-2xs text-[var(--warning)]">
                          Warning: event envelope is missing schema_version.
                        </p>
                      ) : null}
                      {Object.entries(event.payloadObj)
                        .slice(0, 3)
                        .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
                        .join(" | ")}
                    </div>
                  ) : (
                    <p className="mt-1 text-xs text-[var(--primary-600)]">{event.payloadText}</p>
                  )}
                  <p className="mt-1 text-2xs text-[var(--text-caption)]">Event type: {event.eventType}</p>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
