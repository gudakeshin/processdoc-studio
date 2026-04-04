import type { ParsedRunEvent } from "@/lib/runEvents";

export type ReasoningTraceItem = {
  id: string;
  text: string;
  kind: "thinking" | "plan" | "status" | "coordinator" | "tools" | "narrative";
};

/**
 * Merges coordinator_plan, agent_tool_round, narrative thinking, and legacy trace events
 * into one chronological list (order follows parsedEvents).
 */
export function reasoningTraceFromParsedEvents(parsedEvents: ParsedRunEvent[]): ReasoningTraceItem[] {
  const thinkingTrace: ReasoningTraceItem[] = [];

  for (let idx = 0; idx < parsedEvents.length; idx += 1) {
    const ev = parsedEvents[idx];
    const payload = ev.payload || {};

    if (ev.eventType === "status.update") {
      const operation = String(payload.operation ?? payload.status ?? "status");
      thinkingTrace.push({
        id: `status-${idx}`,
        kind: "status",
        text: operation,
      });
    }
    if (ev.eventType === "thinking.start") {
      const statement = String(payload.strategy ?? payload.observation ?? payload.phase ?? "Thinking");
      thinkingTrace.push({
        id: `thinking-${idx}`,
        kind: "thinking",
        text: statement,
      });
    }

    if (ev.eventType.startsWith("plan.")) {
      const phaseRaw = String(payload.phase ?? payload.step ?? payload.status ?? "plan").toLowerCase();
      const phase = phaseRaw.includes("observe")
        ? "observe"
        : phaseRaw.includes("act") || phaseRaw.includes("run")
          ? "act"
          : phaseRaw.includes("report") || phaseRaw.includes("review")
            ? "report"
            : "plan";
      const text = String(payload.taskName ?? payload.taskId ?? payload.step ?? payload.status ?? ev.eventType);
      thinkingTrace.push({
        id: `plan-${idx}`,
        kind: "plan",
        text: `${phase.toUpperCase()}: ${text}`,
      });
    }

    if (ev.eventType === "coordinator_plan" || ev.eventType === "execution_plan") {
      const te = String(payload.thinking_excerpt ?? "").trim();
      if (te) {
        thinkingTrace.push({
          id: `coord-th-${idx}`,
          kind: "coordinator",
          text: `Coordinator thinking: ${te.slice(0, 800)}`,
        });
      }
      const rat = String(payload.rationale ?? "").trim();
      if (rat) {
        thinkingTrace.push({
          id: `coord-rat-${idx}`,
          kind: "coordinator",
          text: `Plan rationale: ${rat.slice(0, 500)}`,
        });
      }
    }

    if (ev.eventType === "agent_tool_round") {
      const agent = String(payload.agent ?? "agent");
      const round = payload.round != null ? String(payload.round) : "?";
      const trace = Array.isArray(payload.trace) ? payload.trace : [];
      const tools = trace
        .map((t) =>
          typeof t === "object" && t !== null && "tool" in t ? String((t as { tool?: string }).tool ?? "") : "",
        )
        .filter(Boolean);
      const toolStr = tools.length ? tools.join(", ") : "(no tools)";
      thinkingTrace.push({
        id: `tool-${idx}`,
        kind: "tools",
        text: `${agent} · round ${round}: ${toolStr}`,
      });
    }

    if (ev.eventType === "narrative_thinking_excerpt") {
      const te = String(payload.thinking_excerpt ?? "").trim();
      if (te) {
        thinkingTrace.push({
          id: `narr-${idx}`,
          kind: "narrative",
          text: `Narrative thinking: ${te.slice(0, 800)}`,
        });
      }
    }
  }

  return thinkingTrace;
}
