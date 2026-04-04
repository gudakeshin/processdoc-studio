"use client";

import { useState } from "react";
import type { TodoChecklistState } from "@/hooks/useTodoChecklistState";
import { TodoItem } from "@/components/run-studio/TodoItem";

export function TodoChecklist({
  checklist,
  onTaskAction,
}: {
  checklist: TodoChecklistState;
  onTaskAction?: (taskId: string, action: "retry" | "skip" | "approve") => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({
    observe: true,
    plan: true,
    act: true,
    report: true,
  });
  return (
    <div className="space-y-2 rounded border border-[var(--surface-border)] bg-white p-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[var(--text-default)]">To-do checklist</p>
        <p className="text-2xs text-[var(--text-muted)]">
          {checklist.progress.completed}/{checklist.progress.total} ({checklist.progress.percentComplete}%)
        </p>
      </div>
      {checklist.phases.map((phaseBlock) => (
        <section key={phaseBlock.phase} className="rounded border border-[var(--surface-border)]">
          <button
            type="button"
            className="flex w-full items-center justify-between bg-[var(--surface-muted)] px-2 py-1 text-left text-2xs font-medium uppercase"
            onClick={() => setOpen((prev) => ({ ...prev, [phaseBlock.phase]: !prev[phaseBlock.phase] }))}
          >
            <span>{phaseBlock.phase}</span>
            <span>
              {phaseBlock.completed}/{phaseBlock.total}
            </span>
          </button>
          {open[phaseBlock.phase] && phaseBlock.tasks.length > 0 ? (
            <ul className="space-y-1 p-1.5">
              {phaseBlock.tasks.map((task) => (
                <TodoItem key={task.id} task={task} onAction={onTaskAction} />
              ))}
            </ul>
          ) : null}
        </section>
      ))}
    </div>
  );
}
