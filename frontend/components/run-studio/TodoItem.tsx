"use client";

import type { TodoTask } from "@/hooks/useTodoChecklistState";

const STATUS_ICON: Record<TodoTask["status"], string> = {
  queued: "⬜",
  in_progress: "→",
  completed: "✓",
  failed: "✗",
  blocked: "⊘",
  skipped: "⊘",
};

export function TodoItem({
  task,
  onAction,
}: {
  task: TodoTask;
  onAction?: (taskId: string, action: "retry" | "skip" | "approve") => void;
}) {
  return (
    <li className="flex items-center justify-between gap-2 rounded border border-[var(--surface-border)] px-2 py-1.5">
      <span className="min-w-0 truncate text-xs text-[var(--text-default)]">
        {STATUS_ICON[task.status]} {task.title}
      </span>
      <div className="flex items-center gap-1">
        {task.status === "failed" ? (
          <button type="button" className="text-2xs underline" onClick={() => onAction?.(task.id, "retry")}>
            Retry
          </button>
        ) : null}
        {task.status !== "completed" && task.status !== "skipped" ? (
          <button type="button" className="text-2xs underline" onClick={() => onAction?.(task.id, "skip")}>
            Skip
          </button>
        ) : null}
        {task.status === "blocked" ? (
          <button type="button" className="text-2xs underline" onClick={() => onAction?.(task.id, "approve")}>
            Approve
          </button>
        ) : null}
      </div>
    </li>
  );
}
