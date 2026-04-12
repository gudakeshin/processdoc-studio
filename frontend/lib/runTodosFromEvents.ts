/**
 * Derives the latest run checklist from persisted SSE / poll lines
 * (`eventType: JSON payload`).
 *
 * Backend `run-events-v1` stores logical fields under `payload` when
 * `event_contract_strict` is true; merge before reading `todos` / `tasks`.
 *
 * Handles both:
 * - `run_todo_snapshot` events (traditional format with todos array)
 * - `coordinator_state_event` events (agentic loop task_board format)
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

/** Convert coordinator task_board to RunTodoRow format.
 *
 * Task board is a dict: {task_id: {id, label, status, phase, ...}}
 * We convert to array of RunTodoRow, sorted by phase.
 */
function coordinatorStateToTodoRows(taskBoard: Record<string, any>): RunTodoRow[] {
  if (!taskBoard || typeof taskBoard !== "object" || Array.isArray(taskBoard)) {
    return [];
  }

  const PHASE_ORDER: Record<string, number> = {
    setup: 0,
    generation: 1,
    finalization: 2,
  };

  // Convert task_board object to array and sort by phase
  const entries = Object.entries(taskBoard)
    .map(([id, task]) => ({
      id,
      label: task.label || id,
      status: task.status || "queued",
      phase: task.phase || "unknown",
      created_at: task.created_at || "",
    }))
    .sort((a, b) => {
      const phaseA = PHASE_ORDER[a.phase] ?? 99;
      const phaseB = PHASE_ORDER[b.phase] ?? 99;
      if (phaseA !== phaseB) return phaseA - phaseB;
      // Secondary sort by creation time
      return a.created_at.localeCompare(b.created_at);
    });

  return entries.map(({ id, label, status }) => ({ id, label, status }));
}

export function runTodosFromEvents(eventLines: string[]): RunTodoRow[] {
  let latest: RunTodoRow[] = [];
  for (const line of eventLines) {
    let raw: string | null = null;
    if (line.startsWith("run_todo_snapshot:")) {
      raw = line.slice("run_todo_snapshot:".length).trim();
    } else if (line.startsWith("todo.checklist_created:")) {
      raw = line.slice("todo.checklist_created:".length).trim();
    } else if (line.startsWith("coordinator_state_event:")) {
      raw = line.slice("coordinator_state_event:".length).trim();
      try {
        const data = JSON.parse(raw);
        if (data.tasks && typeof data.tasks === "object") {
          const rows = coordinatorStateToTodoRows(data.tasks);
          if (rows.length > 0) latest = rows;
        }
      } catch {
        /* ignore malformed state event */
      }
      continue;
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
