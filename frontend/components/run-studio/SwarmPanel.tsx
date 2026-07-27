"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { extractApiErrorMessage, parseResponseBodyLoose } from "@/lib/api-error";
import { useAuth } from "@/lib/auth-context";

type SwarmSummary = {
  team: { id: string; name: string; status: string };
  teammates: Array<{ id: string; teammate_id: string; role: string; status: string }>;
  ready_task_ids: string[];
};

type SwarmMessage = {
  id: string;
  from_teammate: string;
  to_teammate: string | null;
  body: string;
  created_at: string | null;
};

type SwarmTask = {
  id: string;
  title: string;
  status: string;
  phase: string;
  depends_on: string[];
  assigned_teammate_id: string | null;
  blocked_reason: string | null;
};

export function SwarmPanel({
  pid,
  rid,
  liveEventsLength,
}: {
  pid: string;
  rid: string;
  /** Bump when SSE delivers new events (e.g. swarm_message). */
  liveEventsLength: number;
}) {
  const { token, api } = useAuth();
  const [disabled, setDisabled] = useState<string | null>(null);
  const [summary, setSummary] = useState<SwarmSummary | null>(null);
  const [messages, setMessages] = useState<SwarmMessage[]>([]);
  const [tasks, setTasks] = useState<SwarmTask[]>([]);
  const [msgBody, setMsgBody] = useState("");
  const [fromTeammate, setFromTeammate] = useState("teammate-1");
  const [busy, setBusy] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newDepends, setNewDepends] = useState("");
  const [newAssignee, setNewAssignee] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState("");

  const base = `/api/runs/${encodeURIComponent(pid)}/${encodeURIComponent(rid)}/swarm`;

  const refresh = useCallback(async () => {
    if (!token || !pid || !rid) return;
    setBusy(true);
    setDisabled(null);
    setTaskError(null);
    try {
      const q = statusFilter.trim() ? `?status=${encodeURIComponent(statusFilter.trim())}` : "";
      const [sRes, mRes, tRes] = await Promise.all([
        api(`${base}`),
        api(`${base}/messages`),
        api(`${base}/tasks${q}`),
      ]);
      const { data: sData, rawText: sRaw } = await parseResponseBodyLoose(sRes);
      if (sRes.status === 403) {
        const d = (sData && typeof sData === "object" ? sData : {}) as { detail?: string };
        setDisabled(typeof d.detail === "string" ? d.detail : "Swarm API disabled");
        setSummary(null);
        return;
      }
      if (!sRes.ok) {
        setDisabled(extractApiErrorMessage(sData, sRaw || "Could not load swarm summary"));
        return;
      }
      if (!sData || typeof sData !== "object") {
        setDisabled(sRaw ? sRaw.slice(0, 200) : "Could not load swarm summary");
        return;
      }
      setSummary(sData as SwarmSummary);
      if (mRes.ok) {
        const { data: mData } = await parseResponseBodyLoose(mRes);
        const mJson = (mData && typeof mData === "object" ? mData : {}) as { items?: SwarmMessage[] };
        setMessages(Array.isArray(mJson.items) ? mJson.items : []);
      }
      if (tRes.ok) {
        const { data: tData } = await parseResponseBodyLoose(tRes);
        const tJson = (tData && typeof tData === "object" ? tData : {}) as { items?: SwarmTask[] };
        setTasks(Array.isArray(tJson.items) ? tJson.items : []);
      } else if (tRes.status !== 403) {
        setTaskError("Could not load tasks");
      }
    } finally {
      setBusy(false);
    }
  }, [api, base, pid, rid, token, statusFilter]);

  // Refetch when live stream appends events (e.g. swarm_message from start_run instruction broadcast).
  useEffect(() => {
    void refresh();
  }, [refresh, liveEventsLength]);

  // Independent polling for task board updates (every 1.5 seconds)
  // Complements SSE-driven refresh to reduce stale task data
  useEffect(() => {
    const interval = setInterval(() => {
      void refresh();
    }, 1500); // Poll every 1.5 seconds

    return () => clearInterval(interval);
  }, [refresh]);

  const sendMessage = async (broadcast: boolean) => {
    if (!msgBody.trim() || !token) return;
    setBusy(true);
    try {
      const url = broadcast ? `${base}/broadcast` : `${base}/messages`;
      const body = broadcast
        ? { from_teammate: fromTeammate, body: msgBody.trim() }
        : { from_teammate: fromTeammate, body: msgBody.trim() };
      const res = await api(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setMsgBody("");
        void refresh();
      }
    } finally {
      setBusy(false);
    }
  };

  const createTask = async () => {
    if (!newTitle.trim() || !token) return;
    setBusy(true);
    setTaskError(null);
    try {
      const depends_on = newDepends
        .split(/[,;\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await api(`${base}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: newTitle.trim(),
          depends_on,
          phase: "custom",
          assigned_teammate_id: newAssignee.trim() || null,
        }),
      });
      if (res.status === 403) {
        setTaskError("You need Editor role to create tasks.");
        return;
      }
      if (!res.ok) {
        const d = (await res.json().catch(() => ({}))) as { detail?: string };
        setTaskError(typeof d.detail === "string" ? d.detail : "Create failed");
        return;
      }
      setNewTitle("");
      setNewDepends("");
      setNewAssignee("");
      void refresh();
    } finally {
      setBusy(false);
    }
  };

  const patchTaskStatus = async (taskId: string, status: string) => {
    if (!token) return;
    setBusy(true);
    setTaskError(null);
    try {
      const res = await api(`${base}/tasks/${encodeURIComponent(taskId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (res.status === 403) {
        setTaskError("You need Editor role to update tasks.");
        return;
      }
      if (!res.ok) {
        const d = (await res.json().catch(() => ({}))) as { detail?: string };
        setTaskError(typeof d.detail === "string" ? d.detail : "Update failed");
        return;
      }
      void refresh();
    } finally {
      setBusy(false);
    }
  };

  if (disabled) {
    return (
      <div className="rounded-lg border border-[var(--surface-border)] bg-[var(--surface-muted)] p-3 text-xs text-[var(--text-muted)]">
        <strong>Swarm</strong> — {disabled}
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="rounded-lg border border-[var(--surface-border)] bg-white p-3 text-xs text-[var(--text-muted)]">
        <strong>Swarm</strong> — {busy ? "Loading…" : "No data"}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[var(--surface-border)] bg-white p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <strong>Swarm team</strong>
        <Button type="button" variant="secondary" className="min-h-8 px-2 py-1 text-2xs" disabled={busy} onClick={() => void refresh()}>
          Refresh
        </Button>
      </div>
      <p className="mt-1 text-[var(--text-muted)]">
        Team <code className="mono">{summary.team.name}</code> · ready tasks: {summary.ready_task_ids.length}
      </p>
      <ul className="mt-2 space-y-1">
        {summary.teammates.map((m) => (
          <li key={m.id} className="flex justify-between gap-2">
            <span className="mono">{m.teammate_id}</span>
            <span className="text-[var(--text-muted)]">
              {m.role} · {m.status}
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-3 border-t border-[var(--surface-border)] pt-2">
        <strong>Tasks</strong>
        {taskError ? <p className="mt-1 text-red-600">{taskError}</p> : null}
        <div className="mt-1 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-2xs text-[var(--text-muted)]">Status filter</span>
            <select
              className="rounded border border-[var(--surface-border)] bg-white px-2 py-1"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">All</option>
              <option value="queued">queued</option>
              <option value="in_progress">in_progress</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
              <option value="blocked">blocked</option>
              <option value="skipped">skipped</option>
            </select>
          </label>
        </div>
        <div className="mt-2 max-h-48 overflow-auto rounded border border-[var(--surface-border)]">
          <table className="w-full border-collapse text-left text-2xs">
            <thead className="sticky top-0 bg-[var(--surface-muted)]">
              <tr>
                <th className="border-b border-[var(--surface-border)] px-1 py-1">Id</th>
                <th className="border-b border-[var(--surface-border)] px-1 py-1">Title</th>
                <th className="border-b border-[var(--surface-border)] px-1 py-1">Status</th>
                <th className="border-b border-[var(--surface-border)] px-1 py-1">Phase</th>
                <th className="border-b border-[var(--surface-border)] px-1 py-1">Deps</th>
                <th className="border-b border-[var(--surface-border)] px-1 py-1">Assignee</th>
                <th className="border-b border-[var(--surface-border)] px-1 py-1">Set</th>
              </tr>
            </thead>
            <tbody>
              {tasks.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-2 py-2 text-[var(--text-muted)]">
                    No tasks
                  </td>
                </tr>
              ) : (
                tasks.map((t) => (
                  <tr key={t.id} className="border-b border-[var(--surface-border)]">
                    <td className="mono px-1 py-0.5 align-top">{t.id}</td>
                    <td className="px-1 py-0.5 align-top">{t.title}</td>
                    <td className="px-1 py-0.5 align-top">{t.status}</td>
                    <td className="px-1 py-0.5 align-top">{t.phase}</td>
                    <td className="mono px-1 py-0.5 align-top text-[var(--text-muted)]">
                      {(t.depends_on || []).join(", ") || "—"}
                    </td>
                    <td className="mono px-1 py-0.5 align-top">{t.assigned_teammate_id ?? "—"}</td>
                    <td className="px-1 py-0.5 align-top">
                      <select
                        className="max-w-[100px] rounded border border-[var(--surface-border)] bg-white px-1 py-0.5"
                        value=""
                        disabled={busy}
                        onChange={(e) => {
                          const v = e.target.value;
                          e.target.value = "";
                          if (v) void patchTaskStatus(t.id, v);
                        }}
                      >
                        <option value="">—</option>
                        <option value="queued">queued</option>
                        <option value="in_progress">in_progress</option>
                        <option value="completed">completed</option>
                        <option value="failed">failed</option>
                        <option value="blocked">blocked</option>
                        <option value="skipped">skipped</option>
                      </select>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="mt-2 flex flex-col gap-2 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] p-2">
          <span className="font-semibold">New task (Editors)</span>
          <input
            className="w-full rounded border border-[var(--surface-border)] bg-white px-2 py-1"
            aria-label="Task title"
            placeholder="Title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <input
            className="w-full rounded border border-[var(--surface-border)] bg-white px-2 py-1"
            aria-label="Depends on task IDs (comma-separated)"
            placeholder="Depends on task ids (comma-separated)"
            value={newDepends}
            onChange={(e) => setNewDepends(e.target.value)}
          />
          <select
            className="rounded border border-[var(--surface-border)] bg-white px-2 py-1"
            value={newAssignee}
            onChange={(e) => setNewAssignee(e.target.value)}
          >
            <option value="">Unassigned</option>
            {summary.teammates.map((m) => (
              <option key={m.id} value={m.teammate_id}>
                {m.teammate_id}
              </option>
            ))}
          </select>
          <Button type="button" className="min-h-8 w-fit" disabled={busy || !newTitle.trim()} onClick={() => void createTask()}>
            Create task
          </Button>
        </div>
      </div>

      <div className="mt-3 border-t border-[var(--surface-border)] pt-2">
        <strong>Messages</strong>
        <div className="mt-1 max-h-40 space-y-1 overflow-y-auto">
          {messages.length === 0 ? <p className="text-[var(--text-muted)]">No messages yet.</p> : null}
          {messages.map((m) => (
            <div key={m.id} className="rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-2 py-1">
              <span className="font-semibold">{m.from_teammate}</span>
              {m.to_teammate ? <span className="text-[var(--text-muted)]"> → {m.to_teammate}</span> : null}
              <p className="whitespace-pre-wrap text-[var(--text-default)]">{m.body}</p>
            </div>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-2xs text-[var(--text-muted)]">From</span>
            <select
              className="rounded border border-[var(--surface-border)] bg-white px-2 py-1"
              value={fromTeammate}
              onChange={(e) => setFromTeammate(e.target.value)}
            >
              {summary.teammates.map((m) => (
                <option key={m.id} value={m.teammate_id}>
                  {m.teammate_id}
                </option>
              ))}
            </select>
          </label>
          <label className="min-w-[180px] flex-1">
            <span className="sr-only">Message</span>
            <input
              className="w-full rounded border border-[var(--surface-border)] px-2 py-1"
              placeholder="Message body…"
              value={msgBody}
              onChange={(e) => setMsgBody(e.target.value)}
            />
          </label>
          <Button type="button" className="min-h-8" disabled={busy || !msgBody.trim()} onClick={() => void sendMessage(false)}>
            Send
          </Button>
          <Button type="button" variant="secondary" className="min-h-8" disabled={busy || !msgBody.trim()} onClick={() => void sendMessage(true)}>
            Broadcast
          </Button>
        </div>
      </div>
    </div>
  );
}
