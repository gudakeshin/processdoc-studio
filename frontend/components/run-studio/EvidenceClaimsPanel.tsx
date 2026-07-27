"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/apiClient";
import { Button } from "@/components/ui/Button";

type Claim = {
  id: string;
  claim: string;
  claim_type?: string;
  slide_index?: number;
  slide_title?: string;
  status?: string;
  decision?: string;
  citation?: string | null;
  context?: string;
  note?: string;
};

type Dossier = {
  claims: Claim[];
  summary?: {
    total?: number;
    unsupported?: number;
    pending?: number;
    accepted?: number;
    rejected?: number;
    grounded?: number;
  };
};

export function EvidenceClaimsPanel({
  projectId,
  runId,
  enabled,
}: {
  projectId: string;
  runId: string;
  enabled: boolean;
}) {
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled || !projectId || !runId) return;
    try {
      const res = await apiFetch(
        `/api/runs/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}/evidence-claims`
      );
      if (!res.ok) {
        setError("Could not load evidence claims");
        return;
      }
      const data = (await res.json()) as Dossier;
      setDossier(data);
      setError(null);
    } catch {
      setError("Could not load evidence claims");
    }
  }, [enabled, projectId, runId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const decide = async (id: string, decision: "accept" | "reject") => {
    setBusy(true);
    try {
      const res = await apiFetch(
        `/api/runs/${encodeURIComponent(projectId)}/${encodeURIComponent(runId)}/evidence-claims`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decisions: [{ id, decision }] }),
        }
      );
      if (!res.ok) {
        setError("Failed to save decision");
        return;
      }
      const data = (await res.json()) as Dossier;
      setDossier(data);
      setError(null);
    } catch {
      setError("Failed to save decision");
    } finally {
      setBusy(false);
    }
  };

  if (!enabled) return null;

  const unsupported = (dossier?.claims || []).filter((c) => c.status === "unsupported");
  const pending = unsupported.filter((c) => (c.decision || "pending") === "pending");
  const summary = dossier?.summary;

  if (!dossier || (unsupported.length === 0 && (summary?.total || 0) === 0)) {
    return (
      <div className="rounded border border-[var(--surface-border)] bg-[var(--surface-raised)] p-3 text-xs text-[var(--text-muted)]">
        No numeric claims pending review.
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded border border-[var(--surface-border)] bg-[var(--surface-raised)] p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[var(--text-default)]">Evidence claims</p>
          <p className="text-2xs text-[var(--text-muted)]">
            Accept or reject each unsupported figure before Final Approve.
            {typeof summary?.pending === "number" ? ` ${summary.pending} pending.` : null}
          </p>
        </div>
        <Button type="button" variant="secondary" className="text-2xs" disabled={busy} onClick={() => void refresh()}>
          Refresh
        </Button>
      </div>
      {error ? <p className="text-2xs text-[var(--status-error)]">{error}</p> : null}
      {pending.length === 0 && unsupported.length > 0 ? (
        <p className="text-2xs text-[var(--status-ok)]">All unsupported claims reviewed.</p>
      ) : null}
      <ul className="max-h-64 space-y-2 overflow-auto">
        {unsupported.map((c) => {
          const decision = c.decision || "pending";
          return (
            <li
              key={c.id}
              className="rounded border border-[var(--surface-border)] bg-[var(--surface-base)] p-2 text-xs"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-semibold text-[var(--text-default)]">{c.claim}</span>
                <span className="text-2xs uppercase tracking-wide text-[var(--text-caption)]">
                  {decision}
                </span>
              </div>
              <p className="mt-0.5 text-2xs text-[var(--text-muted)]">
                Slide {c.slide_index}
                {c.slide_title ? ` · ${c.slide_title}` : ""}
                {c.claim_type ? ` · ${c.claim_type}` : ""}
              </p>
              {c.context ? (
                <p className="mt-1 line-clamp-2 text-2xs text-[var(--text-caption)]">{c.context}</p>
              ) : null}
              <div className="mt-2 flex gap-2">
                <Button
                  type="button"
                  className="text-2xs"
                  disabled={busy || decision === "accept"}
                  onClick={() => void decide(c.id, "accept")}
                >
                  Accept
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  className="text-2xs"
                  disabled={busy || decision === "reject"}
                  onClick={() => void decide(c.id, "reject")}
                >
                  Reject
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
