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

const STATUS_LABEL: Record<TodoTask["status"], string> = {
  queued: "queued",
  in_progress: "in progress",
  completed: "completed",
  failed: "failed",
  blocked: "blocked",
  skipped: "skipped",
};

export function TodoItem({
  task,
  onAction,
}: {
  task: TodoTask;
  onAction?: (taskId: string, action: "retry" | "skip" | "approve") => void;
}) {
  const handleRetry = () => onAction?.(task.id, "retry");
  const handleSkip = () => onAction?.(task.id, "skip");
  const handleApprove = () => onAction?.(task.id, "approve");

  return (
    <li
      className="flex items-center justify-between gap-2 rounded border border-[var(--surface-border)] px-2 py-1.5"
      aria-label={`${task.title} — ${STATUS_LABEL[task.status]}`}
    >
      <span className="min-w-0 truncate text-xs text-[var(--text-default)]">
        <span aria-hidden="true">{STATUS_ICON[task.status]} </span>
        {task.title}
      </span>
      <div className="flex items-center gap-1">
        {task.status === "failed" ? (
          <button
            type="button"
            className="text-2xs underline"
            aria-label={`Retry task: ${task.title}`}
            onClick={handleRetry}
          >
            Retry
          </button>
        ) : null}
        {task.status !== "completed" && task.status !== "skipped" ? (
          <button
            type="button"
            className="text-2xs underline"
            aria-label={`Skip task: ${task.title}`}
            onClick={handleSkip}
          >
            Skip
          </button>
        ) : null}
        {task.status === "blocked" ? (
          <button
            type="button"
            className="text-2xs underline"
            aria-label={`Approve task: ${task.title}`}
            onClick={handleApprove}
          >
            Approve
          </button>
        ) : null}
      </div>
    </li>
  );
}
