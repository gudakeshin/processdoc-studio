"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { formatCostCompact } from "@/lib/formatTokens";
import type { RunRow } from "@/types/api";

const TERMINAL_STATUSES = new Set(["review_ready", "done", "failed"]);

export type LiveUsage = {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cost_usd: number | null;
  live: boolean;
};

/** Sum token counts and cost across all completed runs for the project. */
export function computeProjectTotals(runs: RunRow[]): {
  totalTokens: number;
  totalCost: number;
  costLabel: string;
} {
  let totalTokens = 0;
  let totalCost = 0;
  for (const r of runs) {
    totalTokens +=
      (r.tokens_input ?? 0) +
      (r.tokens_output ?? 0) +
      (r.tokens_cache_read ?? 0) +
      (r.tokens_cache_creation ?? 0);
    totalCost += r.cost_usd ?? 0;
  }
  return { totalTokens, totalCost, costLabel: formatCostCompact(totalCost) };
}

/**
 * Poll the backend for live token usage while a run is executing.
 * Falls back to DB values when the run has completed.
 */
export function useLiveTokens(
  pid: string,
  rid: string | null,
  runStatus: string,
): {
  data: LiveUsage | null;
  isLive: boolean;
} {
  const { api, token } = useAuth();
  const isExecuting = Boolean(rid) && !TERMINAL_STATUSES.has(runStatus) && runStatus !== "idle";

  const query = useQuery({
    queryKey: ["run-live-usage", pid, rid],
    enabled: Boolean(token && pid && rid),
    refetchInterval: isExecuting ? 2000 : false,
    queryFn: async (): Promise<LiveUsage | null> => {
      if (!rid) return null;
      const res = await api(
        `/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/usage`,
      );
      if (!res.ok) return null;
      const data = await res.json().catch(() => null);
      if (!data) return null;
      return {
        input_tokens: Number(data.input_tokens ?? 0),
        output_tokens: Number(data.output_tokens ?? 0),
        cache_read_tokens: Number(data.cache_read_tokens ?? 0),
        cache_creation_tokens: Number(data.cache_creation_tokens ?? 0),
        cost_usd: data.cost_usd != null ? Number(data.cost_usd) : null,
        live: Boolean(data.live),
      };
    },
  });

  return { data: query.data ?? null, isLive: isExecuting };
}

/**
 * Always-on project session token counter.
 * Polls /api/projects/{pid}/token-usage every 3 s so the UI updates during
 * conversation (chat) and during runs.  Slows to 10 s when idle.
 */
export function useProjectTokenUsage(
  pid: string,
  isActive: boolean,
): LiveUsage | null {
  const { api, token } = useAuth();

  const query = useQuery({
    queryKey: ["project-token-usage", pid],
    enabled: Boolean(token && pid),
    refetchInterval: isActive ? 3000 : 10000,
    queryFn: async (): Promise<LiveUsage | null> => {
      const res = await api(`/api/projects/${encodeURIComponent(pid)}/token-usage`);
      if (!res.ok) return null;
      const data = await res.json().catch(() => null);
      if (!data) return null;
      return {
        input_tokens: Number(data.input_tokens ?? 0),
        output_tokens: Number(data.output_tokens ?? 0),
        cache_read_tokens: Number(data.cache_read_tokens ?? 0),
        cache_creation_tokens: Number(data.cache_creation_tokens ?? 0),
        cost_usd: data.cost_usd != null ? Number(data.cost_usd) : null,
        live: isActive,
      };
    },
  });

  return query.data ?? null;
}
