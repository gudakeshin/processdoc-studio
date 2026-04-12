"use client";

export type CoworkEventType =
  | "message.start"
  | "message.token"
  | "message.done"
  | "thinking.start"
  | "skill.loading"
  | "skill.completed"
  | "skill.error"
  | "plan.phase_start"
  | "plan.task_start"
  | "plan.task_complete"
  | "plan.phase_complete"
  | "questions.refresh"
  | "status.update"
  | "todo.checklist_created"
  | "task.started"
  | "task.progress"
  | "task.completed"
  | "task.failed"
  | "task.blocked"
  | "task.skipped"
  | "task.retrying"
  | "task.intervention_requested"
  | "task.intervention_applied"
  | "coordinator_state_event"
  | "scheduled_task.created"
  | "scheduled_task.updated"
  | "scheduled_task.run_started"
  | "scheduled_task.run_completed";

export type ParsedRunEvent = {
  id?: number;
  eventType: string;
  payload: Record<string, unknown>;
  phase?: string;
  tsMs?: number;
};

export function parseEventLine(line: string): ParsedRunEvent | null {
  const sep = line.indexOf(":");
  if (sep < 0) return null;
  const eventType = line.slice(0, sep).trim();
  const payloadText = line.slice(sep + 1).trim();
  try {
    const parsed = JSON.parse(payloadText) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const payload = (parsed.payload && typeof parsed.payload === "object" ? parsed.payload : parsed) as Record<string, unknown>;
    return {
      eventType,
      payload,
      phase: typeof parsed.phase === "string" ? parsed.phase : undefined,
      tsMs: typeof parsed.ts_ms === "number" ? parsed.ts_ms : undefined,
    };
  } catch {
    return null;
  }
}
