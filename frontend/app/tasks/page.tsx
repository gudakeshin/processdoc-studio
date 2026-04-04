"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useAuth } from "@/lib/auth-context";

export default function TasksPage() {
  const { api } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [instruction, setInstruction] = useState("");
  const [cadence, setCadence] = useState("60");
  const [tasks, setTasks] = useState<any[]>([]);
  const [runsByTask, setRunsByTask] = useState<Record<string, any[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [loadBusy, setLoadBusy] = useState(false);

  async function load() {
    if (!projectId.trim()) return;
    setLoadBusy(true);
    setError(null);
    try {
      const res = await api(`/api/tasks/${encodeURIComponent(projectId.trim())}`);
      const data = (await res.json().catch(() => ({}))) as { detail?: string; items?: any[] };
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Failed to load tasks");
        return;
      }
      setTasks(Array.isArray(data.items) ? data.items : []);
    } finally {
      setLoadBusy(false);
    }
  }

  async function createTask() {
    if (!projectId.trim() || !name.trim() || !instruction.trim()) return;
    setError(null);
    const res = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId.trim(),
        name,
        instruction,
        output_types: ["narrative", "raci", "sop", "process_map"],
        cadence_minutes: Number.parseInt(cadence, 10) || 60,
      }),
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: string };
    if (!res.ok) {
      setError(typeof data.detail === "string" ? data.detail : "Failed to create task");
      return;
    }
    setName("");
    setInstruction("");
    await load();
  }

  async function runNow(taskId: string) {
    const res = await api(`/api/tasks/${encodeURIComponent(projectId.trim())}/${encodeURIComponent(taskId)}/run-now`, {
      method: "POST",
    });
    if (!res.ok) {
      setError("Failed to queue task run");
    } else {
      await load();
    }
  }

  async function setTaskStatus(taskId: string, action: "pause" | "resume") {
    const res = await api(`/api/tasks/${encodeURIComponent(projectId.trim())}/${encodeURIComponent(taskId)}/${action}`, {
      method: "POST",
    });
    if (!res.ok) {
      setError(`Failed to ${action} task`);
      return;
    }
    await load();
  }

  async function loadRuns(taskId: string) {
    const res = await api(`/api/tasks/${encodeURIComponent(projectId.trim())}/${encodeURIComponent(taskId)}/runs`);
    const data = (await res.json().catch(() => ({}))) as { items?: any[] };
    if (res.ok) {
      setRunsByTask((prev) => ({ ...prev, [taskId]: Array.isArray(data.items) ? data.items : [] }));
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-[var(--text-default)]">Scheduled Tasks</h1>
      <p className="text-sm text-[var(--text-caption)]">
        Create recurring autonomous runs (CoWork-style) and trigger run-now.
      </p>
      <Card className="space-y-3 p-4">
        <Input
          placeholder="Project ID (e.g. p_xxx)"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        />
        <Button type="button" variant="secondary" onClick={() => void load()} disabled={loadBusy}>
          {loadBusy ? "Loading…" : "Load tasks"}
        </Button>
      </Card>
      <Card className="space-y-3 p-4">
        <p className="font-medium text-[var(--text-default)]">Create scheduled task</p>
        <Input placeholder="Task name" value={name} onChange={(e) => setName(e.target.value)} />
        <Textarea placeholder="Instruction" value={instruction} onChange={(e) => setInstruction(e.target.value)} rows={4} />
        <Input placeholder="Cadence minutes" value={cadence} onChange={(e) => setCadence(e.target.value)} />
        <Button type="button" onClick={() => void createTask()}>
          Create
        </Button>
      </Card>
      {error ? <div className="alert alert--error">{error}</div> : null}
      <div className="space-y-2">
        {tasks.map((task) => (
          <Card key={task.id} className="space-y-2 p-4 text-sm">
            <p className="font-medium text-[var(--text-default)]">{task.name}</p>
            <p className="text-[var(--text-muted)]">{task.instruction}</p>
            <p className="text-2xs text-[var(--text-caption)]">next_run_at: {task.next_run_at ?? "-"}</p>
            <Button type="button" variant="primary" className="mt-1 min-h-9" onClick={() => void runNow(task.id)}>
              Run now
            </Button>
            <div className="flex gap-2">
              {task.status === "active" ? (
                <Button type="button" variant="secondary" className="min-h-9" onClick={() => void setTaskStatus(task.id, "pause")}>
                  Pause
                </Button>
              ) : (
                <Button type="button" variant="secondary" className="min-h-9" onClick={() => void setTaskStatus(task.id, "resume")}>
                  Resume
                </Button>
              )}
              <Button type="button" variant="ghost" className="min-h-9" onClick={() => void loadRuns(task.id)}>
                History
              </Button>
            </div>
            {Array.isArray(runsByTask[task.id]) && runsByTask[task.id].length > 0 ? (
              <div className="rounded border border-[var(--surface-border)] p-2 text-2xs">
                {runsByTask[task.id].slice(0, 5).map((r) => (
                  <p key={r.id}>
                    {r.created_at ?? "-"} · {r.status} · {r.run_id ?? "n/a"}
                  </p>
                ))}
              </div>
            ) : null}
          </Card>
        ))}
      </div>
    </div>
  );
}
