/**
 * Derives the latest run checklist from persisted SSE / poll lines
 * (`eventType: JSON payload`).
 *
 * Backend `run-events-v1` stores logical fields under `payload` when
 * `event_contract_strict` is true; merge before reading `todos` / `tasks`.
 */

export type RunTodoRow = {
  id: string;
  label: string;
  status: string;
};

function isTodoRow(x: unknown): x is RunTodoRow {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.label === "string" &&
    typeof o.status === "string"
  );
}

/** Merge strict envelope `payload` into a flat view (inner keys win). */
export function mergeRunEventEnvelope(root: Record<string, unknown>): Record<string, unknown> {
  const inner = root.payload;
  if (inner && typeof inner === "object" && !Array.isArray(inner)) {
    return { ...root, ...(inner as Record<string, unknown>) };
  }
  return root;
}

/**
 * Parse `run_todo_snapshot` or `todo.checklist_created` JSON (envelope or legacy flat).
 * Uses `todos` or `tasks` array.
 */
export function extractRunTodoRowsFromEventData(data: unknown): RunTodoRow[] {
  if (!data || typeof data !== "object" || Array.isArray(data)) return [];
  const merged = mergeRunEventEnvelope(data as Record<string, unknown>);
  const rawTodos = merged.todos;
  const rawTasks = merged.tasks;
  const arr = Array.isArray(rawTodos) ? rawTodos : Array.isArray(rawTasks) ? rawTasks : [];
  return arr.filter(isTodoRow);
}

export function runTodosFromEvents(eventLines: string[]): RunTodoRow[] {
  let latest: RunTodoRow[] = [];
  for (const line of eventLines) {
    let raw: string | null = null;
    if (line.startsWith("run_todo_snapshot:")) {
      raw = line.slice("run_todo_snapshot:".length).trim();
    } else if (line.startsWith("todo.checklist_created:")) {
      raw = line.slice("todo.checklist_created:".length).trim();
    } else {
      continue;
    }
    try {
      const rows = extractRunTodoRowsFromEventData(JSON.parse(raw));
      if (rows.length > 0) latest = rows;
    } catch {
      /* ignore malformed snapshot */
    }
  }
  return latest;
}
