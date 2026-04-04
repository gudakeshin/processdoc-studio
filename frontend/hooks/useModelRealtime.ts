"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth-context";
import { fetchModelEvents, modelWsUrl, type ModelRealtimeEvent } from "@/lib/realtime";

type ConnectionState = "connected" | "reconnecting" | "degraded";

export function useModelRealtime(projectId: string, modelId: string) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [connectionState, setConnectionState] = useState<ConnectionState>("reconnecting");
  const [lastEventId, setLastEventId] = useState(0);
  const lastEventIdRef = useRef(0);

  const wsUrl = useMemo(
    () => (token ? modelWsUrl(token, projectId, modelId) : ""),
    [projectId, modelId, token]
  );

  useEffect(() => {
    if (!token || !projectId || !modelId) return;
    let cancelled = false;
    let retryMs = 1000;
    let socket: WebSocket | null = null;
    let invalidateTimer: ReturnType<typeof setTimeout> | null = null;
    let needsInvalidate = false;

    const flushInvalidations = () => {
      if (!needsInvalidate) return;
      needsInvalidate = false;
      void qc.invalidateQueries({ queryKey: ["model-dashboard", projectId, modelId] });
      void qc.invalidateQueries({ queryKey: ["model-conflicts", projectId, modelId] });
      void qc.invalidateQueries({ queryKey: ["model", projectId, modelId] });
    };

    const queueInvalidation = () => {
      needsInvalidate = true;
      if (invalidateTimer) return;
      invalidateTimer = setTimeout(() => {
        invalidateTimer = null;
        flushInvalidations();
      }, 400);
    };

    const applyEvent = (eventType: string) => {
      if (eventType === "model_ws_connected") return;
      queueInvalidation();
    };
    const applyEventEnvelope = (payload: Partial<ModelRealtimeEvent> & { event_type?: string; type?: string }) => {
      const eventId = typeof payload.event_id === "number" ? payload.event_id : 0;
      if (eventId > 0) {
        setLastEventId((prev) => {
          const next = eventId > prev ? eventId : prev;
          lastEventIdRef.current = next;
          return next;
        });
      }
      if (payload.event_type) applyEvent(payload.event_type);
      if (payload.type) applyEvent(payload.type);
    };

    const replayGap = async () => {
      const events = await fetchModelEvents(token, projectId, modelId, lastEventIdRef.current);
      for (const event of events) applyEventEnvelope(event);
    };

    const connect = () => {
      if (cancelled) return;
      setConnectionState("reconnecting");
      socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        retryMs = 1000;
        setConnectionState("connected");
        void replayGap();
      };
      socket.onmessage = async (msg) => {
        try {
          const payload = JSON.parse(msg.data) as { event_id?: number; event_type?: string; type?: string };
          applyEventEnvelope(payload);
        } catch {
          // ignore malformed message
        }
      };
      socket.onclose = () => {
        if (cancelled) return;
        setConnectionState("reconnecting");
        setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 10000);
      };
      socket.onerror = () => {
        setConnectionState("degraded");
        // SSE/poll-style fallback over the same events endpoint.
        void replayGap();
      };
    };

    connect();
    return () => {
      cancelled = true;
      socket?.close();
      if (invalidateTimer) {
        clearTimeout(invalidateTimer);
      }
    };
  }, [token, projectId, modelId, wsUrl, qc]);

  return { connectionState, lastEventId };
}

