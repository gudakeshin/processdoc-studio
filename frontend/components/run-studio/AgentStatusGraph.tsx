"use client";

import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import { useMemo } from "react";
import { toolCallsFromAgentRoundPayload } from "@/lib/agentToolRound";

type AgentNode = {
  id: string;
  label: string;
  status: "queued" | "running" | "done" | "failed";
  tools: number;
  /** Registry tool ids invoked by this agent (deduped, order preserved). */
  toolNames: string[];
};

function parseEventLine(line: string): { eventType: string; payload: Record<string, unknown> | null } {
  const sep = line.indexOf(":");
  const eventType = (sep >= 0 ? line.slice(0, sep) : "step").trim();
  const payloadText = (sep >= 0 ? line.slice(sep + 1) : line).trim();
  try {
    const parsed = JSON.parse(payloadText);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { eventType, payload: parsed as Record<string, unknown> };
    }
  } catch {
    // noop
  }
  return { eventType, payload: null };
}

function computeNodes(events: string[]): AgentNode[] {
  const map = new Map<string, AgentNode>();
  for (const line of events) {
    const { eventType, payload } = parseEventLine(line);
    if (!payload) continue;
    if (eventType === "step") {
      const name = String(payload.skill_name ?? payload.agent ?? payload.output_type ?? "Agent");
      const key = name.toLowerCase();
      const statusRaw = String(payload.status ?? "").toLowerCase();
      const existing =
        map.get(key) ?? { id: key, label: name, status: "queued", tools: 0 as number, toolNames: [] as string[] };
      if (statusRaw.includes("fail") || statusRaw.includes("error")) existing.status = "failed";
      else if (
        statusRaw.includes("post_processing_done") ||
        (statusRaw.includes("processing_done") && statusRaw.includes("post"))
      )
        existing.status = "done";
      else if (statusRaw.includes("done") || statusRaw.includes("finish") || statusRaw.includes("complet"))
        existing.status = "done";
      else if (
        statusRaw.includes("post_processing_start") ||
        (statusRaw.includes("post_processing") && !statusRaw.includes("done"))
      )
        existing.status = "running";
      else if (statusRaw.includes("run") || statusRaw.includes("start")) existing.status = "running";
      else if (statusRaw.includes("enqueued") || statusRaw.includes("queue")) existing.status = "queued";
      map.set(key, existing);
    }
    if (eventType === "agent_tool_round") {
      const name = String(payload.skill_name ?? payload.agent ?? payload.output_type ?? "Agent");
      const key = name.toLowerCase();
      const existing =
        map.get(key) ?? { id: key, label: name, status: "running", tools: 0, toolNames: [] as string[] };
      for (const row of toolCallsFromAgentRoundPayload(payload)) {
        if (!existing.toolNames.includes(row.name)) {
          existing.toolNames.push(row.name);
        }
      }
      existing.tools += 1;
      if (existing.status !== "failed" && existing.status !== "done") existing.status = "running";
      map.set(key, existing);
    }
  }
  return Array.from(map.values());
}

function statusSurfaceClass(s: AgentNode["status"]) {
  switch (s) {
    case "done":
      return "status-surface--done";
    case "failed":
      return "status-surface--failed";
    case "running":
      return "status-surface--running";
    default:
      return "status-surface--queued";
  }
}

function StatusGlyph({ status }: { status: AgentNode["status"] }) {
  const common = "h-4 w-4 shrink-0";
  switch (status) {
    case "done":
      return <CheckCircle2 className={common} aria-hidden />;
    case "failed":
      return <XCircle className={common} aria-hidden />;
    case "running":
      return <Loader2 className={`${common} animate-spin`} aria-hidden />;
    default:
      return <CircleDashed className={common} aria-hidden />;
  }
}

function statusLabel(status: AgentNode["status"]) {
  switch (status) {
    case "done":
      return "Completed";
    case "failed":
      return "Failed";
    case "running":
      return "Running";
    default:
      return "Queued";
  }
}

export function AgentStatusGraph({ events }: { events: string[] }) {
  const nodes = useMemo(() => computeNodes(events), [events]);
  if (nodes.length === 0) {
    return (
      <div className="deloitte-surface p-3 text-2xs text-[var(--text-caption)]">
        Agent graph will appear once execution events begin.
      </div>
    );
  }
  return (
    <div className="deloitte-surface p-3">
      <p className="text-2xs font-semibold text-[var(--text-default)]">Agent execution graph</p>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        {nodes.map((n) => (
          <div
            key={n.id}
            className={`flex min-h-11 flex-col gap-1 rounded border px-2 py-2 text-2xs ${statusSurfaceClass(n.status)}`}
            role="group"
            aria-label={`${n.label}, ${statusLabel(n.status)}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 font-medium break-words">
                <StatusGlyph status={n.status} />
                {n.label}
              </span>
              <span className="rounded bg-[color:color-mix(in_srgb,white_55%,transparent)] px-2 py-1 text-[0.65rem] font-medium uppercase tracking-wide">
                {n.status}
              </span>
            </div>
            <p className="text-2xs opacity-90">
              Tool rounds: {n.tools}
              {n.toolNames.length > 0 ? (
                <span className="mt-0.5 block font-medium text-[var(--text-default)]">{n.toolNames.join(", ")}</span>
              ) : null}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
