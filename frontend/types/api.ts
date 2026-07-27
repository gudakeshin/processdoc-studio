/** Shared API response shapes aligned with backend routes. */

export type ProjectRow = { id: string; name: string };
export type ProjectsListResponse = { items: ProjectRow[] };

export type RunRow = {
  id: string;
  status: string;
  created_at: string | null;
  instruction: string;
  tokens_input?: number | null;
  tokens_output?: number | null;
  tokens_cache_read?: number | null;
  tokens_cache_creation?: number | null;
  cost_usd?: number | null;
};

export type RunsListResponse = { items: RunRow[] };

export type RunEventItem = { id: number; event_type: string; payload: Record<string, unknown> };
export type RunEventsResponse = {
  run_id: string;
  status: string;
  plan?: unknown;
  items: RunEventItem[];
};

export type RunTask = {
  id: string;
  title: string;
  status: string;
  phase: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
};

export type RunTasksResponse = {
  run_id: string;
  project_id: string;
  items: RunTask[];
};
