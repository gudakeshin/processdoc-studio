"use client";

import { useMemo, useState } from "react";

type TaskStatus = "completed" | "in-progress" | "queued" | "blocked" | "error";
type Phase = "observe" | "plan" | "act" | "report";

type OparTask = {
  id: string;
  text: string;
  status: TaskStatus;
};

type OparStage = {
  phase: Phase;
  tasks: OparTask[];
};

const DEFAULT_STAGES: OparStage[] = [
  { phase: "observe", tasks: [] },
  { phase: "plan", tasks: [] },
  { phase: "act", tasks: [] },
  { phase: "report", tasks: [] },
];

function statusFromRaw(raw: string): TaskStatus {
  const value = raw.toLowerCase();
  if (value.includes("fail") || value.includes("error")) return "error";
  if (value.includes("block")) return "blocked";
  if (value.includes("done") || value.includes("complete") || value.includes("finish")) return "completed";
  if (value.includes("start") || value.includes("run") || value.includes("progress")) return "in-progress";
  return "queued";
}

function inferPhase(stepName: string): Phase {
  const s = stepName.toLowerCase();
  if (s.includes("coordinator") || s.includes("observe") || s.includes("load") || s.includes("validate")) return "observe";
  if (s.includes("plan") || s.includes("route")) return "plan";
  if (s.includes("execute") || s.includes("tool") || s.includes("agent") || s.includes("output")) return "act";
  return "report";
}

function iconForStatus(status: TaskStatus): string {
  if (status === "completed") return "✓";
  if (status === "in-progress") return "→";
  if (status === "blocked") return "⊘";
  if (status === "error") return "✗";
  return "⌛";
}

export function OPARPanel({ events, openQuestionsCount }: { events: string[]; openQuestionsCount: number }) {
  const [expanded, setExpanded] = useState<Record<Phase, boolean>>({
    observe: true,
    plan: true,
    act: false,
    report: false,
  });

  const stages = useMemo(() => {
    const byPhase: Record<Phase, OparTask[]> = {
      observe: [],
      plan: [],
      act: [],
      report: [],
    };
    let idx = 0;
    for (const line of events) {
      if (!line.startsWith("step:")) continue;
      const payload = line.slice("step:".length).trim();
      try {
        const parsed = JSON.parse(payload) as Record<string, unknown>;
        const rawStatus = String(parsed.status ?? "queued");
        const step = String(parsed.step ?? parsed.skill_name ?? parsed.agent ?? `task-${idx + 1}`);
        const phase = inferPhase(step);
        byPhase[phase].push({
          id: `${phase}-${idx}`,
          text: step.replaceAll("_", " "),
          status: statusFromRaw(rawStatus),
        });
        idx += 1;
      } catch {
        continue;
      }
    }
    const base = DEFAULT_STAGES.map((stage) => ({ ...stage, tasks: byPhase[stage.phase] }));
    if (openQuestionsCount > 0) {
      base[1].tasks.unshift({
        id: "plan-clarifications",
        text: `${openQuestionsCount} clarification(s) pending`,
        status: "in-progress",
      });
    }
    return base;
  }, [events, openQuestionsCount]);

  return (
    <section className="rounded-lg border border-[var(--surface-border)] bg-white p-3">
      <h3 className="text-sm font-semibold">OPAR Plan</h3>
      <div className="mt-2 space-y-2">
        {stages.map((stage) => (
          <div key={stage.phase} className="rounded border border-[var(--surface-border)]">
            <button
              type="button"
              className="flex min-h-11 w-full items-center justify-between px-2 py-1.5 text-left text-xs font-medium"
              aria-expanded={expanded[stage.phase]}
              onClick={() => setExpanded((prev) => ({ ...prev, [stage.phase]: !prev[stage.phase] }))}
            >
              <span className="uppercase">{stage.phase}</span>
              <span className="text-[var(--text-muted)]">{expanded[stage.phase] ? "▼" : "▶"}</span>
            </button>
            {expanded[stage.phase] ? (
              <ul className="space-y-1 border-t border-[var(--surface-border)] px-2 py-2 text-xs">
                {stage.tasks.length === 0 ? (
                  <li className="text-[var(--text-muted)]">No tasks yet</li>
                ) : (
                  stage.tasks.map((task) => (
                    <li key={task.id} className="flex items-start gap-2">
                      <span className="mt-0.5">{iconForStatus(task.status)}</span>
                      <span className={task.status === "queued" ? "text-[var(--text-muted)]" : ""}>{task.text}</span>
                    </li>
                  ))
                )}
              </ul>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
