import { getApiBase, getWsOriginForBrowser } from "@/lib/api";
import { apiFetch } from "@/lib/apiClient";

export type ModelRealtimeEvent = {
  event_id: number;
  event_type: string;
  project_id: string;
  model_id: string;
  server_ts: string;
  payload: Record<string, unknown>;
};

export async function fetchModelEvents(
  token: string,
  projectId: string,
  modelId: string,
  afterEventId: number
): Promise<ModelRealtimeEvent[]> {
  const base = getApiBase();
  const res = await apiFetch(
    `${base}/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/events?after_event_id=${afterEventId}&limit=200`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
  if (!res.ok) return [];
  const data = (await res.json()) as { items?: ModelRealtimeEvent[] };
  return data.items ?? [];
}

export function modelWsUrl(token: string, projectId: string, modelId: string): string {
  const base = getApiBase();
  if (!base) {
    const wsOrigin = getWsOriginForBrowser();
    return `${wsOrigin}/api/ws/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}?token=${encodeURIComponent(token)}`;
  }
  const wsBase = base.startsWith("https://") ? base.replace("https://", "wss://") : base.replace("http://", "ws://");
  return `${wsBase}/api/ws/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}?token=${encodeURIComponent(token)}`;
}

