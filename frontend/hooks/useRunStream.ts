"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getApiBase } from "@/lib/api";
import { extractApiErrorMessage, humanizePlainUpstreamError, parseResponseBodyLoose } from "@/lib/api-error";
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
  const seenEventIdsRef = useRef<Set<number>>(new Set()); // M6: dedup SSE + poll events
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null); // H7: cancel in-flight fetches
  const retryCountRef = useRef(0);
  const connectRef = useRef<(() => void) | null>(null); // H1: allow retryLive to reconnect

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // H7: abort any in-flight fetch and issue a new controller
  const resetAbort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    return abortRef.current.signal;
  }, []);

  const hydrate = useCallback(async () => {
    const signal = resetAbort();
    try {
      const res = await api(
        `/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/events?after_event_id=0`,
        { signal }
      );
      if (signal.aborted) return;
      const { data: parsedJson, rawText } = await parseResponseBodyLoose(res);
      if (signal.aborted) return;
      if (!res.ok) {
        const errPayload = parsedJson && typeof parsedJson === "object" ? parsedJson : {};
        setError(extractApiErrorMessage(errPayload, rawText || "Failed to load run events"));
        return;
      }
      if (parsedJson === null || typeof parsedJson !== "object") {
        setError(
          rawText
            ? humanizePlainUpstreamError(rawText.slice(0, 300))
            : "Run events response was not valid JSON",
        );
        return;
      }
      const validated = runEventsResponseSchema.safeParse(parsedJson);
      if (!validated.success) {
        setError("Run events payload validation failed");
        return;
      }
      setError(null);
      const data = validated.data as unknown as EventsResponse;
      const seen = new Set<number>();
      const lines: string[] = [];
      const parsed: ParsedRunEvent[] = [];
      let max = 0;
      for (const it of data.items) {
        seen.add(it.id);
        max = Math.max(max, it.id);
        const line = eventItemToLine(it);
        lines.push(line);
        const p = parseEventLine(line);
        if (p) parsed.push(p);
      }
      seenEventIdsRef.current = seen;
      lastEventIdRef.current = max;
      setStatus(data.status);
      setEvents(lines);
      setParsedEvents(parsed);
      if (TERMINAL_RUN_STATES.has(data.status)) {
        stopPolling();
      }
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") return;
      setError("Failed to load run events");
    }
  }, [api, pid, rid, stopPolling, resetAbort]);

  const pollOnce = useCallback(async () => {
    if (!abortRef.current || abortRef.current.signal.aborted) return;
    const signal = abortRef.current.signal;
    try {
      const res = await api(
        `/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/events?after_event_id=${lastEventIdRef.current}`,
        { signal }
      );
      if (signal.aborted) return;
      const { data: parsedJson, rawText } = await parseResponseBodyLoose(res);
      if (signal.aborted) return;
      if (!res.ok) {
        const errPayload = parsedJson && typeof parsedJson === "object" ? parsedJson : {};
        setError(extractApiErrorMessage(errPayload, rawText || "Failed to poll run events"));
        return;
      }
      if (parsedJson === null || typeof parsedJson !== "object") {
        setError(
          rawText
            ? humanizePlainUpstreamError(rawText.slice(0, 300))
            : "Run events response was not valid JSON",
        );
        return;
      }
      const validated = runEventsResponseSchema.safeParse(parsedJson);
      if (!validated.success) {
        setError("Run events payload validation failed");
        return;
      }
      setError(null);
      const data = validated.data as unknown as EventsResponse;
      // M6: deduplicate against events already received via SSE
      const newItems = data.items.filter((it) => !seenEventIdsRef.current.has(it.id));
      if (newItems.length) {
        const max = Math.max(...newItems.map((x) => x.id), lastEventIdRef.current);
        lastEventIdRef.current = max;
        for (const it of newItems) seenEventIdsRef.current.add(it.id);
        const lines = newItems.map(eventItemToLine);
        const parsed = lines.map((line) => parseEventLine(line)).filter((x): x is ParsedRunEvent => Boolean(x));
        setEvents((prev) => [...prev, ...lines]);
        setParsedEvents((prev) => [...prev, ...parsed]);
      }
      setStatus(data.status);
      if (TERMINAL_RUN_STATES.has(data.status)) {
        stopPolling();
      }
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") return;
    }
  }, [api, pid, rid, stopPolling]);

  useEffect(() => {
    if (!token || !pid || !rid) return;

    // Reset dedup state for new run
    seenEventIdsRef.current = new Set();
    lastEventIdRef.current = 0;
    retryCountRef.current = 0;

    // Initialise an AbortController for this effect instance
    abortRef.current = new AbortController();

    const hydrateTimer = window.setTimeout(() => {
      void hydrate();
    }, 0);

    const connect = () => {
      esRef.current?.close();
      const url = `${getApiBase()}/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/stream?token=${encodeURIComponent(token)}&after_event_id=${lastEventIdRef.current}`;
      const es = new EventSource(url);
      esRef.current = es;

      const on = (name: string) =>
        es.addEventListener(name, (event) => {
          const ev = event as MessageEvent;
          const numId = Number(ev.lastEventId) || 0;
          if (ev.lastEventId) {
            // M6: skip events already delivered via polling fallback
            if (seenEventIdsRef.current.has(numId)) return;
            seenEventIdsRef.current.add(numId);
            lastEventIdRef.current = Math.max(lastEventIdRef.current, numId);
          }
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
        retryCountRef.current = 0;
        setError(null);
        // H1: if we reconnected successfully after poll mode, exit poll mode
        if (pollRef.current) {
          stopPolling();
          setPollMode(false);
        }
      };
      es.onerror = () => {
        es.close();
        retryCountRef.current += 1;
        if (retryCountRef.current >= 3) {
          setPollMode(true);
          setError(
            "Live stream reconnecting failed; using periodic refresh for run updates (execution may still proceed).",
          );
          void pollOnce();
          if (!pollRef.current) {
            pollRef.current = setInterval(() => void pollOnce(), 1500);
          }
          // H1: schedule SSE retry after 60 s so poll mode doesn't persist indefinitely
          setTimeout(() => {
            if (pollRef.current) {
              retryCountRef.current = 0;
              connect();
            }
          }, 60_000);
          return;
        }
        setTimeout(connect, 1000 * retryCountRef.current);
      };
    };

    // Expose connect so retryLive can call it
    connectRef.current = connect;
    connect();

    return () => {
      window.clearTimeout(hydrateTimer);
      esRef.current?.close();
      stopPolling();
      abortRef.current?.abort(); // H7: cancel any pending fetch
    };
  }, [token, pid, rid, hydrate, pollOnce, stopPolling, resetAbort]);

  // H1: retryLive restarts SSE (not just a one-shot hydrate)
  const retryLive = useCallback(() => {
    stopPolling();
    setPollMode(false);
    setError(null);
    retryCountRef.current = 0;
    connectRef.current?.();
  }, [stopPolling]);

  return { events, parsedEvents, status, error, pollMode, retryLive };
}
