"use client";

import { useMemo, useState } from "react";

import type { ChatMessage } from "@/hooks/useRunStudio";
import type { ParsedRunEvent } from "@/lib/runEvents";
import { reasoningTraceFromParsedEvents, type ReasoningTraceItem } from "@/lib/reasoningTraceFromEvents";

type PlanTaskStatus = "completed" | "in-progress" | "queued" | "blocked" | "error";
type PlanPhase = "observe" | "plan" | "act" | "report";

export type CoworkPlanTask = { id: string; text: string; status: PlanTaskStatus };
export type CoworkPlanStage = { phase: PlanPhase; tasks: CoworkPlanTask[] };

export type CoworkSkill = { id: string; name: string; status: "queued" | "active" | "completed" | "error" };
export type ThinkingTraceItem = ReasoningTraceItem;

export function useCoworkState(params: {
  parsedEvents: ParsedRunEvent[];
  messages: ChatMessage[];
  openQuestions: string[];
}) {
  const { parsedEvents, messages, openQuestions } = params;
  const [rightPanelTab, setRightPanelTab] = useState<"plan" | "questions" | "status">("plan");
  const [expandedPlanStages, setExpandedPlanStages] = useState<Record<PlanPhase, boolean>>({
    observe: true,
    plan: true,
    act: false,
    report: false,
  });
  const [thinkingExpanded, setThinkingExpanded] = useState(false);

  const derived = useMemo(() => {
    const stages: Record<PlanPhase, CoworkPlanTask[]> = { observe: [], plan: [], act: [], report: [] };
    const skills = new Map<string, CoworkSkill>();
    let operation = "Ready";
    const thinkingTrace = reasoningTraceFromParsedEvents(parsedEvents);
    const thinkingStatements: string[] = [];

    for (let idx = 0; idx < parsedEvents.length; idx += 1) {
      const ev = parsedEvents[idx];
      const payload = ev.payload || {};

      if (ev.eventType === "status.update") {
        operation = String(payload.operation ?? payload.status ?? operation);
      }
      if (ev.eventType === "thinking.start") {
        const statement = String(payload.strategy ?? payload.observation ?? payload.phase ?? "Thinking");
        thinkingStatements.push(statement);
      }
      if (ev.eventType === "skill.loading") {
        const name = String(payload.skill_name ?? payload.skill ?? payload.output_type ?? "Tool");
        skills.set(name, { id: name.toLowerCase().replace(/\s+/g, "-"), name, status: "active" });
      }
      if (ev.eventType === "skill.completed") {
        const name = String(payload.skill_name ?? payload.skill ?? payload.output_type ?? "Tool");
        skills.set(name, { id: name.toLowerCase().replace(/\s+/g, "-"), name, status: "completed" });
      }
      if (ev.eventType === "skill.error") {
        const name = String(payload.skill_name ?? payload.skill ?? payload.output_type ?? "Tool");
        skills.set(name, { id: name.toLowerCase().replace(/\s+/g, "-"), name, status: "error" });
      }

      if (ev.eventType === "coordinator_plan" || ev.eventType === "execution_plan") {
        const te = String(payload.thinking_excerpt ?? "").trim();
        if (te) {
          thinkingStatements.push(te.slice(0, 220));
        }
      }
      if (ev.eventType === "narrative_thinking_excerpt") {
        const te = String(payload.thinking_excerpt ?? "").trim();
        if (te) {
          thinkingStatements.push(`Narrative: ${te.slice(0, 180)}`);
        }
      }

      if (ev.eventType.startsWith("plan.")) {
        const phaseRaw = String(payload.phase ?? payload.step ?? payload.status ?? "plan").toLowerCase();
        const phase: PlanPhase = phaseRaw.includes("observe")
          ? "observe"
          : phaseRaw.includes("act") || phaseRaw.includes("run")
            ? "act"
            : phaseRaw.includes("report") || phaseRaw.includes("review")
              ? "report"
              : "plan";
        const text = String(payload.taskName ?? payload.taskId ?? payload.step ?? payload.status ?? ev.eventType);
        const taskStatus: PlanTaskStatus = ev.eventType === "plan.task_complete"
          ? "completed"
          : ev.eventType === "plan.task_start"
            ? "in-progress"
            : String(payload.status ?? "").includes("block")
              ? "blocked"
              : String(payload.status ?? "").includes("fail")
                ? "error"
                : "queued";
        stages[phase].push({ id: `${phase}-${idx}`, text, status: taskStatus });
        if (ev.eventType === "plan.task_start" || ev.eventType === "plan.phase_start") {
          thinkingStatements.push(text);
        }
      }
    }

    const normalizedStages: CoworkPlanStage[] = (["observe", "plan", "act", "report"] as PlanPhase[]).map((phase) => ({
      phase,
      tasks: stages[phase],
    }));
    const activeSkills = [...skills.values()];
    const streamingMessage = messages.length > 0 ? messages[messages.length - 1] : null;

    return {
      plan: normalizedStages,
      skills: activeSkills,
      hasThinkingTrace: thinkingTrace.length > 0,
      thinkingStatements: thinkingStatements.slice(-3),
      thinkingTrace: thinkingTrace.slice(-25),
      status: {
        operation,
        skillsLoaded: {
          active: activeSkills.filter((s) => s.status === "active").length,
          total: activeSkills.length,
        },
      },
      questions: openQuestions,
      streamingMessage,
    };
  }, [messages, openQuestions, parsedEvents]);

  return {
    ...derived,
    rightPanelTab,
    setRightPanelTab,
    expandedPlanStages,
    setExpandedPlanStages,
    thinkingExpanded,
    setThinkingExpanded,
  };
}
