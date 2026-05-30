"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { extractApiErrorMessage, parseResponseBodyLoose } from "@/lib/api-error";
import { useAuth } from "@/lib/auth-context";
import { getWsOriginForBrowser } from "@/lib/api";

export type CellLock = {
  cellRef: string;
  lockedBy: string;
  lockedAt: string;
  version: number;
  status: "locked" | "unlocked" | "conflicted";
  expiresAt?: string;
};

export type PresenceEntry = {
  email: string;
  connectedAt: string;
  cursor: string | null;
};

export function useCollaborativeLocks(projectId: string, modelId: string) {
  const { api, token } = useAuth();
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const [wsLocks, setWsLocks] = useState<CellLock[] | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [presence, setPresence] = useState<PresenceEntry[]>([]);

  // WebSocket connection
  useEffect(() => {
    if (!projectId || !modelId || !token) return;

    const wsUrl = `${getWsOriginForBrowser()}/api/ws/models/${encodeURIComponent(projectId)}/${encodeURIComponent(modelId)}/collab?token=${encodeURIComponent(token)}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => { setWsConnected(false); wsRef.current = null; };
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data as string) as { type: string; locks?: CellLock[]; presence?: PresenceEntry[] };
        if (msg.type === "init" || msg.type === "lock_update") {
          setWsLocks(msg.locks ?? []);
        }
        if (msg.type === "init" || msg.type === "presence_update") {
          setPresence(msg.presence ?? []);
        }
      } catch {
        // ignore malformed frames
      }
    };

    return () => {
      ws.close();
    };
  }, [projectId, modelId, token]);

  // Polling fallback when WebSocket is not connected
  const poll = useQuery({
    queryKey: ["collab-locks", projectId, modelId],
    enabled: Boolean(token && projectId && modelId && !wsConnected),
    refetchInterval: 5000,
    queryFn: async (): Promise<CellLock[]> => {
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/collaborative/locks`
      );
      const { data: parsed, rawText } = await parseResponseBodyLoose(res);
      const data = (parsed && typeof parsed === "object" ? parsed : {}) as { locks?: CellLock[]; detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, rawText || "Load locks failed"));
      return data.locks ?? [];
    },
  });

  const locks = wsLocks ?? poll.data ?? [];

  function sendWs(msg: Record<string, unknown>) {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }

  function onRetry(cellRef: string) {
    sendWs({ action: "lock", cellRef });
  }

  const forceRelease = useMutation({
    mutationFn: async ({ cellRef }: { cellRef: string }) => {
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/collaborative/locks/${encodeURIComponent(cellRef)}`,
        { method: "DELETE" }
      );
      const { data: parsed, rawText } = await parseResponseBodyLoose(res);
      const data = (parsed && typeof parsed === "object" ? parsed : {}) as { detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, rawText || "Force release failed"));
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["collab-locks", projectId, modelId] });
    },
  });

  return {
    locks,
    presence,
    wsConnected,
    onRetry,
    onForceRelease: (cellRef: string, _userId: string) => forceRelease.mutate({ cellRef }),
  };
}
