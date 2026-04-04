"use client";

import { useMemo, useState } from "react";

import {
  useModelConflicts,
  useReopenModelConflict,
  useResolveModelConflict,
  type ModelConflict,
} from "@/hooks/useModels";

function ValueCell({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-[var(--primary-400)]">null</span>;
  if (typeof value === "string") return <span className="font-mono">{value}</span>;
  if (typeof value === "number" || typeof value === "boolean") return <span className="font-mono">{String(value)}</span>;
  return <span className="font-mono">{JSON.stringify(value)}</span>;
}

export function ConflictResolutionPanel({ projectId, modelId }: { projectId: string; modelId: string }) {
  const [sheet, setSheet] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [message, setMessage] = useState("");

  const conflicts = useModelConflicts(projectId, modelId, {
    sheet: sheet || undefined,
    severity: severity || undefined,
    status: status || undefined,
  });
  const resolveMutation = useResolveModelConflict(projectId, modelId);
  const reopenMutation = useReopenModelConflict(projectId, modelId);

  const items = conflicts.data ?? [];
  const sheets = useMemo(
    () => Array.from(new Set((conflicts.data ?? []).map((x) => x.sheet))).sort(),
    [conflicts.data]
  );

  async function resolve(item: ModelConflict, chosenSide: "local" | "remote" | "policy") {
    setMessage("");
    try {
      await resolveMutation.mutateAsync({
        conflictId: item.id,
        chosen_side: chosenSide,
        rationale: chosenSide === "policy" ? "bulk policy resolve" : "manual resolve",
      });
      setMessage(`Resolved ${item.cell_ref} with ${chosenSide}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Resolve failed");
    }
  }

  async function reopen(item: ModelConflict) {
    setMessage("");
    try {
      await reopenMutation.mutateAsync({ conflictId: item.id, reason: "manual reopen from conflict center" });
      setMessage(`Reopened ${item.cell_ref}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Reopen failed");
    }
  }

  return (
    <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 space-y-3 shadow-sm">
      <h3 className="text-base font-semibold">Conflict Center (Per-Cell Diff)</h3>
      <p className="text-sm text-[var(--primary-700)]">
        Review base/local/remote values and resolve high-risk formula/type/structural conflicts before sync continues.
      </p>

      <div className="grid gap-2 md:grid-cols-3">
        <select className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] p-2 text-sm" value={sheet} onChange={(e) => setSheet(e.target.value)}>
          <option value="">All sheets</option>
          {sheets.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] p-2 text-sm"
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
        >
          <option value="">All severities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
        </select>
        <select className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] p-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
        </select>
      </div>

      {conflicts.isLoading ? <p className="text-sm text-[var(--primary-700)]">Loading conflicts...</p> : null}
      {items.length === 0 && !conflicts.isLoading ? <p className="text-sm text-[var(--primary-700)]">No conflicts found.</p> : null}

      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id} className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded bg-[color:color-mix(in_srgb,var(--primary-100)_80%,white)] px-2 py-1">{item.sheet}</span>
              <span className="rounded bg-[color:color-mix(in_srgb,var(--primary-100)_80%,white)] px-2 py-1">{item.cell_ref}</span>
              <span className="rounded bg-[color:color-mix(in_srgb,var(--accent-green)_18%,white)] px-2 py-1 text-[var(--accent-green-dark)]">{item.type}</span>
              <span className="rounded bg-[color:color-mix(in_srgb,var(--accent-blue)_16%,white)] px-2 py-1 text-[var(--accent-indigo)]">{item.severity}</span>
              <span className="rounded bg-[color:color-mix(in_srgb,var(--accent-blue)_12%,white)] px-2 py-1 text-[var(--accent-indigo)]">{item.status}</span>
            </div>

            <div className="grid gap-2 md:grid-cols-3 text-sm">
              <div className="rounded border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] p-2">
                <p className="mb-1 text-xs font-semibold text-[var(--primary-600)]">Base</p>
                <ValueCell value={item.base?.value} />
              </div>
              <div className="rounded border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] p-2">
                <p className="mb-1 text-xs font-semibold text-[var(--primary-600)]">Local</p>
                <ValueCell value={item.local?.value} />
              </div>
              <div className="rounded border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] p-2">
                <p className="mb-1 text-xs font-semibold text-[var(--primary-600)]">Remote</p>
                <ValueCell value={item.remote?.value} />
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] bg-white px-3 py-1.5 text-xs text-[var(--primary-900)] hover:bg-[var(--primary-50)]"
                disabled={item.status === "resolved" || resolveMutation.isPending}
                onClick={() => void resolve(item, "local")}
              >
                Keep local
              </button>
              <button
                type="button"
                className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] bg-white px-3 py-1.5 text-xs text-[var(--primary-900)] hover:bg-[var(--primary-50)]"
                disabled={item.status === "resolved" || resolveMutation.isPending}
                onClick={() => void resolve(item, "remote")}
              >
                Keep remote
              </button>
              <button
                type="button"
                className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] bg-white px-3 py-1.5 text-xs text-[var(--primary-900)] hover:bg-[var(--primary-50)]"
                disabled={item.status === "resolved" || resolveMutation.isPending}
                onClick={() => void resolve(item, "policy")}
              >
                Resolve by policy
              </button>
              <button
                type="button"
                className="rounded-md bg-[var(--primary-800)] px-3 py-1.5 text-xs text-white hover:bg-[var(--primary-900)]"
                disabled={item.status !== "resolved" || reopenMutation.isPending}
                onClick={() => void reopen(item)}
              >
                Reopen
              </button>
            </div>
          </div>
        ))}
      </div>

      {message ? <p className="text-xs text-[var(--primary-800)]">{message}</p> : null}
    </div>
  );
}

