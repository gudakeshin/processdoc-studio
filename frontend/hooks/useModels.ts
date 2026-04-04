"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth-context";

export type ModelSummary = {
  id: string;
  name: string;
  description?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  version_count?: number;
};

export type Scenario = {
  id: string;
  name: string;
  created_at?: string;
  assumption_overrides: Record<string, string | number | boolean>;
};

export type ModelConflict = {
  id: string;
  sheet: string;
  cell_ref: string;
  type: "value_mismatch" | "type_mismatch" | "formula_changed" | "deleted_range" | "structural_shift";
  severity: "medium" | "high";
  status: "open" | "resolved";
  base?: { value?: unknown };
  local?: { value?: unknown };
  remote?: { value?: unknown };
  resolution?: { chosen_side?: "local" | "remote" | "policy"; rationale?: string; actor?: string; timestamp?: string } | null;
};

export function useModels(projectId: string) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["models", projectId],
    enabled: Boolean(token && projectId),
    queryFn: async (): Promise<ModelSummary[]> => {
      const res = await api(`/api/projects/${encodeURIComponent(projectId)}/models`);
      const data = (await res.json()) as { items?: ModelSummary[]; detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "Failed to load models");
      return data.items ?? [];
    },
  });
}

export function useCreateModel(projectId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { name: string; description?: string; assumptions?: Record<string, unknown> }) => {
      const res = await api(`/api/projects/${encodeURIComponent(projectId)}/models`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const data = (await res.json()) as { id?: string; detail?: string };
      if (!res.ok || !data.id) throw new Error(data.detail ?? "Create model failed");
      return data.id;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["models", projectId] });
    },
  });
}

export function useModelDetail(projectId: string, modelId: string) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["model", projectId, modelId],
    enabled: Boolean(token && projectId && modelId),
    queryFn: async (): Promise<{ model: ModelSummary & { assumptions?: Record<string, unknown> }; scenarios: Scenario[] }> => {
      const res = await api(`/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}`);
      const data = (await res.json()) as {
        model?: ModelSummary & { assumptions?: Record<string, unknown> };
        scenarios?: Scenario[];
        detail?: string;
      };
      if (!res.ok || !data.model) throw new Error(data.detail ?? "Load model failed");
      return { model: data.model, scenarios: data.scenarios ?? [] };
    },
  });
}

export function useModelVersions(projectId: string, modelId: string) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["model-versions", projectId, modelId],
    enabled: Boolean(token && projectId && modelId),
    queryFn: async (): Promise<Array<{ version_id: string; created_at: string; reason: string }>> => {
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/versions`
      );
      const data = (await res.json()) as {
        items?: Array<{ version_id: string; created_at: string; reason: string }>;
        detail?: string;
      };
      if (!res.ok) throw new Error(data.detail ?? "Load versions failed");
      return data.items ?? [];
    },
  });
}

export function useCreateScenario(projectId: string, modelId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { name: string; assumption_overrides: Record<string, unknown> }) => {
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/scenarios`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );
      const data = (await res.json()) as { detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "Create scenario failed");
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["model", projectId, modelId] });
      void qc.invalidateQueries({ queryKey: ["model-versions", projectId, modelId] });
      void qc.invalidateQueries({ queryKey: ["model-dashboard", projectId, modelId] });
    },
  });
}

export function useModelDashboard(projectId: string, modelId: string) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["model-dashboard", projectId, modelId],
    enabled: Boolean(token && projectId && modelId),
    queryFn: async (): Promise<{
      kpis: Array<{ id: string; label: string; value: string | number }>;
      charts: Array<{ id: string; title: string; labels: string[]; datasets: Array<{ label: string; data: number[] }> }>;
      tables: Array<{ id: string; title: string; columns: string[]; rows: Array<Array<string | number | boolean>> }>;
    }> => {
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/dashboard`
      );
      const data = (await res.json()) as any;
      if (!res.ok) throw new Error(data.detail ?? "Load dashboard failed");
      return data;
    },
  });
}

export function useModelConflicts(
  projectId: string,
  modelId: string,
  filters?: { sheet?: string; severity?: string; status?: string }
) {
  const { api, token } = useAuth();
  return useQuery({
    queryKey: ["model-conflicts", projectId, modelId, filters?.sheet, filters?.severity, filters?.status],
    enabled: Boolean(token && projectId && modelId),
    queryFn: async (): Promise<ModelConflict[]> => {
      const params = new URLSearchParams();
      if (filters?.sheet) params.set("sheet", filters.sheet);
      if (filters?.severity) params.set("severity", filters.severity);
      if (filters?.status) params.set("status", filters.status);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/excel/conflicts${suffix}`
      );
      const data = (await res.json()) as { items?: ModelConflict[]; detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "Load conflicts failed");
      return data.items ?? [];
    },
  });
}

export function useResolveModelConflict(projectId: string, modelId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { conflictId: string; chosen_side: "local" | "remote" | "policy"; rationale?: string }) => {
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/excel/conflicts/${encodeURIComponent(payload.conflictId)}/resolve`,
        { method: "POST", body: JSON.stringify({ chosen_side: payload.chosen_side, rationale: payload.rationale ?? "" }) }
      );
      const data = (await res.json()) as { detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "Resolve conflict failed");
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["model-conflicts", projectId, modelId] });
    },
  });
}

export function useReopenModelConflict(projectId: string, modelId: string) {
  const { api } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { conflictId: string; reason?: string }) => {
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/excel/conflicts/${encodeURIComponent(payload.conflictId)}/reopen`,
        { method: "POST", body: JSON.stringify({ reason: payload.reason ?? "" }) }
      );
      const data = (await res.json()) as { detail?: string };
      if (!res.ok) throw new Error(data.detail ?? "Reopen conflict failed");
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["model-conflicts", projectId, modelId] });
    },
  });
}
