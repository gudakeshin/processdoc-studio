"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import { deadLetterResponseSchema, type DeadLetterItem } from "@/lib/apiSchemas";

export type { DeadLetterItem };

/** Poll the run-queue dead-letter list for a project (failed/blocked queue items needing operator action). */
export function useDeadLetterQueueQuery(projectId: string, enabled = true) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["dead-letter", projectId],
    enabled: enabled && Boolean(token && projectId),
    refetchInterval: 8000,
    queryFn: async (): Promise<DeadLetterItem[]> => {
      const res = await api(`/api/runs/${encodeURIComponent(projectId)}/queue/dead-letter`);
      const raw = (await res.json().catch(() => ({}))) as unknown;
      if (!res.ok) throw new Error(extractApiErrorMessage(raw, "Failed to load dead-letter items"));
      const validated = deadLetterResponseSchema.safeParse(raw);
      return validated.success ? validated.data.items ?? [] : [];
    },
  });
}

function useDeadLetterMutation(projectId: string, path: "replay" | "reset-attempts") {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (itemId: string) => {
      const res = await api(`/api/runs/${encodeURIComponent(projectId)}/queue/dead-letter/${path}`, {
        method: "POST",
        body: JSON.stringify({ item_id: itemId }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, `Failed to ${path.replace("-", " ")} item`));
      return itemId;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dead-letter", projectId] });
      void qc.invalidateQueries({ queryKey: ["active-runs", projectId] });
    },
  });
}

export function useReplayDeadLetterMutation(projectId: string) {
  return useDeadLetterMutation(projectId, "replay");
}

export function useResetDeadLetterAttemptsMutation(projectId: string) {
  return useDeadLetterMutation(projectId, "reset-attempts");
}
