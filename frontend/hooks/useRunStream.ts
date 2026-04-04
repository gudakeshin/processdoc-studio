"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getApiBase } from "@/lib/api";
import { extractApiErrorMessage } from "@/lib/api-error";
import { runEventsResponseSchema } from "@/lib/apiSchemas";
import { useAuth } from "@/lib/auth-context";
import { type ParsedRunEvent, parseEventLine } from "@/lib/runEvents";

type RunEventItem = { id: number; event_type: string; payload: unknown };
type EventsResponse = { status: string; items: RunEventItem[]; plan?: unknown };
const TERMINAL_RUN_STATES = new Set(["review_ready", "done", "failed"]);

function runEventPayloadToSseData(payload: unknown): string {
  if (typeof payload === "string") return payload;
  return JSON.stringify(payload);
}

function eventItemToLine(it: { event_type: string; payload: unknown }): string {
  return `${it.event_type}: ${runEventPayloadToSseData(it.payload)}`;
}

export function useRunStream(pid: string, rid: string) {
  const { token, api } = useAuth();
  const [events, setEvents] = useState<string[]>([]);
  const [status, setStatus] = useState<string>("idle");
  const [error, setError] = useState<string | null>(null);
  const [pollMode, setPollMode] = useState(false);
  const [parsedEvents, setParsedEvents] = useState<ParsedRunEvent[]>([]);
  const lastEventIdRef = useRef(0);
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const hydrate = useCallback(async () => {
    const res = await api(`/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/events?after_event_id=0`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(extractApiErrorMessage(body, "Failed to load run events"));
      return;
    }
    const parsedJson = await res.json();
    const validated = runEventsResponseSchema.safeParse(parsedJson);
    if (!validated.success) {
      setError("Run events payload validation failed");
      return;
    }
    setError(null);
    const data = validated.data as unknown as EventsResponse;
    const lines = data.items.map(eventItemToLine);
    const parsed = lines.map((line) => parseEventLine(line)).filter((x): x is ParsedRunEvent => Boolean(x));
    const max = data.items.reduce((acc, it) => Math.max(acc, it.id), 0);
    lastEventIdRef.current = max;
    setStatus(data.status);
    setEvents(lines);
    setParsedEvents(parsed);
    if (TERMINAL_RUN_STATES.has(data.status)) {
      stopPolling();
    }
  }, [api, pid, rid, stopPolling]);

  const pollOnce = useCallback(async () => {
    const res = await api(
      `/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/events?after_event_id=${lastEventIdRef.current}`
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(extractApiErrorMessage(body, "Failed to poll run events"));
      return;
    }
    const parsedJson = await res.json();
    const validated = runEventsResponseSchema.safeParse(parsedJson);
    if (!validated.success) {
      setError("Run events payload validation failed");
      return;
    }
    setError(null);
    const data = validated.data as unknown as EventsResponse;
    const lines = data.items.map(eventItemToLine);
    const parsed = lines.map((line) => parseEventLine(line)).filter((x): x is ParsedRunEvent => Boolean(x));
    if (data.items.length) {
      lastEventIdRef.current = Math.max(...data.items.map((x) => x.id), lastEventIdRef.current);
      setEvents((prev) => [...prev, ...lines]);
      setParsedEvents((prev) => [...prev, ...parsed]);
    }
    setStatus(data.status);
    if (TERMINAL_RUN_STATES.has(data.status)) {
      stopPolling();
    }
  }, [api, pid, rid, stopPolling]);

  useEffect(() => {
    if (!token || !pid || !rid) return;
    let retryCount = 0;
    const hydrateTimer = window.setTimeout(() => {
      void hydrate();
    }, 0);

    const connect = () => {
      const url = `${getApiBase()}/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/stream?token=${encodeURIComponent(token)}&after_event_id=${lastEventIdRef.current}`;
      const es = new EventSource(url);
      esRef.current = es;
      const on = (name: string) =>
        es.addEventListener(name, (event) => {
          const ev = event as MessageEvent;
          if (ev.lastEventId) lastEventIdRef.current = Math.max(lastEventIdRef.current, Number(ev.lastEventId) || 0);
          const line = `${name}: ${ev.data}`;
          setEvents((prev) => [...prev, line]);
          const parsed = parseEventLine(line);
          if (parsed) {
            setParsedEvents((prev) => [...prev, parsed]);
          }
          if (name === "done" || name === "failed") {
            stopPolling();
            setStatus(name);
          }
        });
      [
        "message.start",
        "message.token",
        "message.done",
        "thinking.start",
        "skill.loading",
        "skill.completed",
        "skill.error",
        "plan.phase_start",
        "plan.task_start",
        "plan.task_complete",
        "plan.phase_complete",
        "questions.refresh",
        "status.update",
        "todo.checklist_created",
        "task.started",
        "task.progress",
        "task.completed",
        "task.failed",
        "task.blocked",
        "task.skipped",
        "task.retrying",
        "task.intervention_requested",
        "task.intervention_applied",
        "scheduled_task.created",
        "scheduled_task.updated",
        "scheduled_task.run_started",
        "scheduled_task.run_completed",
        "plan_ready",
        "step",
        "coordinator_plan",
        "execution_plan",
        "agent_tool_round",
        "narrative_thinking_excerpt",
        "quality_gate",
        "evaluator_pipeline",
        "evaluator_retry_requested",
        "output_chunk",
        "qa_report",
        "guardrail_event",
        "guardrail_report",
        "visual_qa_report",
        "run_todo_snapshot",
        "done",
        "failed",
      ].forEach(on);

      es.onopen = () => {
        retryCount = 0;
        setError(null);
      };
      es.onerror = () => {
        es.close();
        retryCount += 1;
        if (retryCount >= 3) {
          setPollMode(true);
          setError(
            "Live stream reconnecting failed; using periodic refresh for run updates (execution may still proceed).",
          );
          void pollOnce();
          pollRef.current = setInterval(() => void pollOnce(), 1500);
          return;
        }
        setTimeout(connect, 1000 * retryCount);
      };
    };
    connect();

    return () => {
      window.clearTimeout(hydrateTimer);
      esRef.current?.close();
      stopPolling();
    };
  }, [token, pid, rid, hydrate, pollOnce, stopPolling]);

  return { events, parsedEvents, status, error, pollMode, retryLive: hydrate };
}
