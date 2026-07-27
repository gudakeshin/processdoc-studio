"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";

export type ActiveRunState = "working" | "hung" | "awaiting_approval" | "blocked" | "queued";

export interface ActiveRunRow {
  id: string;
  status: string;
  state: ActiveRunState;
  stale: boolean;
  created_at: string | null;
  approved_at: string | null;
  latest_event_at: string | null;
  latest_event_type: string | null;
  seconds_since_last_event: number | null;
  instruction: string;
  tokens_input: number | null;
  tokens_output: number | null;
  cost_usd: number | null;
}

export interface ActiveRunsResponse {
  project_id: string;
  stuck_timeout_sec: number;
  items: ActiveRunRow[];
}

/** Poll the agentops health endpoint for in-flight runs and their staleness. */
export function useActiveRunsQuery(projectId: string, enabled = true) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["active-runs", projectId],
    enabled: enabled && Boolean(token && projectId),
    refetchInterval: 4000,
    queryFn: async (): Promise<ActiveRunsResponse> => {
      const res = await api(`/api/runs/${encodeURIComponent(projectId)}/active`);
      const data = (await res.json().catch(() => ({}))) as Partial<ActiveRunsResponse>;
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to load active runs"));
      return {
        project_id: projectId,
        stuck_timeout_sec: Number(data.stuck_timeout_sec ?? 0),
        items: data.items ?? [],
      };
    },
  });
}

/** Pause, resume, or force-stop a run via the shared control endpoint. */
export function useRunControlMutation(projectId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ runId, action }: { runId: string; action: "pause" | "resume" | "stop" }) => {
      const res = await api(
        `/api/runs/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}/control`,
        { method: "POST", body: JSON.stringify({ action }) },
      );
      const data = (await res.json().catch(() => ({}))) as { status?: string; detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, `Failed to ${action} run`));
      return runId;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["active-runs", projectId] });
      void qc.invalidateQueries({ queryKey: ["runs", projectId] });
    },
  });
}

/** Force-stop a run (reuses the existing control endpoint; frees the admission slot). */
export function useStopRunMutation(projectId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (runId: string) => {
      const res = await api(
        `/api/runs/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}/control`,
        { method: "POST", body: JSON.stringify({ action: "stop" }) },
      );
      const data = (await res.json().catch(() => ({}))) as { status?: string; detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to stop run"));
      return runId;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["active-runs", projectId] });
      void qc.invalidateQueries({ queryKey: ["runs", projectId] });
    },
  });
}
