"use client";

import { useMemo } from "react";
import type { ParsedRunEvent } from "@/lib/runEvents";
import type { RunTodoRow } from "@/lib/runTodosFromEvents";

export type TodoTaskStatus = "queued" | "in_progress" | "completed" | "failed" | "blocked" | "skipped";
export type TodoTaskPhase = "observe" | "plan" | "act" | "report";

export type TodoTask = {
  id: string;
  title: string;
  status: TodoTaskStatus;
  phase: TodoTaskPhase;
  durationMs?: number;
};

export type TodoChecklistState = {
  tasks: TodoTask[];
  phases: Array<{ phase: TodoTaskPhase; tasks: TodoTask[]; completed: number; total: number }>;
  progress: { total: number; completed: number; inProgress: number; blocked: number; percentComplete: number };
};

function normalizeStatus(raw: string): TodoTaskStatus {
  const v = String(raw || "").toLowerCase();
  if (v === "pending") return "queued";
  if (v === "running") return "in_progress";
  if (v === "done") return "completed";
  if (v === "queued" || v === "in_progress" || v === "completed" || v === "failed" || v === "blocked" || v === "skipped") return v;
  return "queued";
}

function inferPhase(taskId: string): TodoTaskPhase {
  const id = String(taskId || "").toLowerCase();
  if (id === "context" || id === "process_model") return "observe";
  if (id === "plan") return "plan";
  if (id.startsWith("out:")) return "act";
  return "report";
}

export function useTodoChecklistState(params: {
  parsedEvents: ParsedRunEvent[];
  snapshotRows: RunTodoRow[];
}): TodoChecklistState {
  const { parsedEvents, snapshotRows } = params;

  return useMemo(() => {
    const byId = new Map<string, TodoTask>();
    for (const row of snapshotRows) {
      byId.set(row.id, {
        id: row.id,
        title: row.label,
        status: normalizeStatus(row.status),
        phase: inferPhase(row.id),
      });
    }

    for (const ev of parsedEvents) {
      if (!ev.eventType.startsWith("task.")) continue;
      const taskId = String(ev.payload.task_id ?? ev.payload.id ?? "").trim();
      if (!taskId) continue;
      const title = String(ev.payload.title ?? byId.get(taskId)?.title ?? taskId);
      const status = normalizeStatus(String(ev.payload.status ?? ev.eventType.replace("task.", "")));
      const phase = (String(ev.payload.phase || inferPhase(taskId)).toLowerCase() as TodoTaskPhase);
      byId.set(taskId, {
        id: taskId,
        title,
        status,
        phase: ["observe", "plan", "act", "report"].includes(phase) ? phase : inferPhase(taskId),
        durationMs: typeof ev.payload.duration_ms === "number" ? ev.payload.duration_ms : byId.get(taskId)?.durationMs,
      });
    }

    const tasks = Array.from(byId.values());
    const phaseOrder: TodoTaskPhase[] = ["observe", "plan", "act", "report"];
    const phases = phaseOrder.map((phase) => {
      const rows = tasks.filter((t) => t.phase === phase);
      const completed = rows.filter((t) => t.status === "completed").length;
      return { phase, tasks: rows, completed, total: rows.length };
    });
    const progress = {
      total: tasks.length,
      completed: tasks.filter((t) => t.status === "completed").length,
      inProgress: tasks.filter((t) => t.status === "in_progress").length,
      blocked: tasks.filter((t) => t.status === "blocked").length,
    };
    return {
      tasks,
      phases,
      progress: {
        ...progress,
        percentComplete: progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0,
      },
    };
  }, [parsedEvents, snapshotRows]);
}
