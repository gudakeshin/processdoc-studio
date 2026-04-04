"use client";

import type { RunTodoRow } from "@/lib/runTodosFromEvents";

const STATUS_CLASS: Record<string, string> = {
  pending: "bg-[var(--surface-muted)] text-[var(--text-muted)]",
  running: "bg-[color:color-mix(in_srgb,var(--info)_22%,white)] text-[color:color-mix(in_srgb,var(--info)_78%,black)]",
  done: "bg-[color:color-mix(in_srgb,var(--success)_24%,white)] text-[color:color-mix(in_srgb,var(--success)_80%,black)]",
  failed: "bg-[color:color-mix(in_srgb,var(--error)_24%,white)] text-[var(--error)]",
  skipped: "bg-[var(--surface-muted)] text-[var(--text-muted)] line-through",
};

export function RunChecklist({ todos }: { todos: RunTodoRow[] }) {
  if (todos.length === 0) return null;
  return (
    <div className="rounded-lg border border-[var(--surface-border)] bg-white p-3 text-xs">
      <p className="font-semibold text-[var(--text-default)]">Run checklist</p>
      <ul className="mt-2 space-y-1.5">
        {todos.map((t) => {
          const pill =
            STATUS_CLASS[t.status] ?? "bg-[var(--surface-muted)] text-[var(--text-muted)]";
          return (
            <li key={t.id} className="flex items-start gap-2">
              <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-2xs font-medium uppercase ${pill}`}>
                {t.status}
              </span>
              <span className="min-w-0 flex-1 break-words leading-snug text-[var(--text-default)]">{t.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
