"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import type { RunRow } from "@/types/api";

export type { RunRow };

export class RunCreationError extends Error {
  code?: string;
  inferredTemplateOutputTypes?: string[];
  inferredCustomOutputTypes?: string[];
  inferredOutputTypeRepresentations?: Record<string, string>;
  inferredRationale?: string;
}

export function useRunsQuery(projectId: string, enabled = true) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["runs", projectId],
    enabled: enabled && Boolean(token && projectId),
    queryFn: async (): Promise<RunRow[]> => {
      const res = await api(`/api/runs?project_id=${encodeURIComponent(projectId)}`);
      const data = (await res.json().catch(() => ({}))) as { items?: RunRow[] };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to load runs"));
      return data.items ?? [];
    },
  });
}

export function useCreateRunMutation(projectId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (payload: {
      instruction: string;
      output_types: string[];
      custom_output_types?: string[];
      output_type_representations?: Record<string, string>;
      conversation_id?: string;
      plan_hash?: string;
    }) => {
      const res = await api("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          instruction: payload.instruction,
          output_types: payload.output_types,
          custom_output_types: payload.custom_output_types ?? [],
          output_type_representations: payload.output_type_representations ?? {},
          conversation_id: payload.conversation_id ?? null,
          plan_hash: payload.plan_hash ?? null,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        run_id?: string;
        detail?: string | {
          code?: string;
          message?: string;
          inferred_template_output_types?: string[];
          inferred_custom_output_types?: string[];
          inferred_output_type_representations?: Record<string, string>;
          inferred_rationale?: string;
        };
      };
      if (!res.ok || !data.run_id) {
        const err = new RunCreationError(extractApiErrorMessage(data, "Create run failed"));
        if (data.detail && typeof data.detail === "object") {
          err.code = typeof data.detail.code === "string" ? data.detail.code : undefined;
          err.inferredTemplateOutputTypes = Array.isArray(data.detail.inferred_template_output_types)
            ? data.detail.inferred_template_output_types.map((x) => String(x))
            : [];
          err.inferredCustomOutputTypes = Array.isArray(data.detail.inferred_custom_output_types)
            ? data.detail.inferred_custom_output_types.map((x) => String(x))
            : [];
          err.inferredOutputTypeRepresentations =
            data.detail.inferred_output_type_representations &&
            typeof data.detail.inferred_output_type_representations === "object"
              ? data.detail.inferred_output_type_representations
              : {};
          err.inferredRationale = typeof data.detail.inferred_rationale === "string"
            ? data.detail.inferred_rationale
            : undefined;
        }
        throw err;
      }
      return data.run_id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["runs", projectId] });
    },
  });
}

export function useClearRunsMutation(projectId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const res = await api(`/api/runs/${encodeURIComponent(projectId)}`, {
        method: "DELETE",
      });
      const data = (await res.json().catch(() => ({}))) as { deleted_runs?: number };
      if (!res.ok) {
        throw new Error(extractApiErrorMessage(data, "Failed to clear recent runs"));
      }
      return Number(data.deleted_runs ?? 0);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["runs", projectId] });
    },
  });
}

export function useDeleteRunMutation(projectId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (runId: string) => {
      const res = await api(`/api/runs/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}`, {
        method: "DELETE",
      });
      const data = (await res.json().catch(() => ({}))) as { deleted?: boolean };
      if (!res.ok || !data.deleted) {
        throw new Error(extractApiErrorMessage(data, "Failed to delete run"));
      }
      return runId;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["runs", projectId] });
    },
  });
}
