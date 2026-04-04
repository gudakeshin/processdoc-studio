"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import type { ProjectRow } from "@/types/api";

export type { ProjectRow };

export function useProjectsQuery(enabled = true) {
  const { api, token } = useAuth();

  return useQuery({
    queryKey: ["projects"],
    enabled: enabled && Boolean(token),
    staleTime: 5 * 60 * 1000,
    queryFn: async (): Promise<ProjectRow[]> => {
      const res = await api("/api/projects");
      const data = (await res.json().catch(() => ({}))) as { items?: ProjectRow[] };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to load projects"));
      return data.items ?? [];
    },
  });
}

export function useCreateProjectMutation() {
  const { api } = useAuth();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (name: string) => {
      const res = await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
      const data = (await res.json().catch(() => ({}))) as { id?: string };
      if (!res.ok || !data.id) {
        throw new Error(extractApiErrorMessage(data, "Create failed"));
      }
      return data.id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDeleteProjectMutation() {
  const { api } = useAuth();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (projectId: string) => {
      const res = await api(`/api/projects/${projectId}`, { method: "DELETE" });
      const data = (await res.json().catch(() => ({}))) as { deleted?: boolean };
      if (!res.ok || !data.deleted) {
        throw new Error(extractApiErrorMessage(data, "Delete failed"));
      }
      return projectId;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
