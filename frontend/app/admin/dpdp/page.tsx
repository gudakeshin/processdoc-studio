"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ProjectPicker } from "@/components/admin/ProjectPicker";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";

type Tab = "consent" | "rights" | "incidents" | "data";

type RightsItem = {
  id: string;
  principal_id: string;
  request_type: string;
  status: string;
  details?: string | null;
  created_at?: string | null;
};

type ConsentLedgerRow = {
  id: string;
  principal_id: string;
  purpose: string;
  granted: boolean;
  granted_by?: string | null;
  revoked_at?: string | null;
  created_at?: string | null;
};

const INCIDENT_STATES = ["open", "triaged", "investigating", "resolved", "closed"] as const;

export default function AdminDpdpPage() {
  const { api, token } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [tab, setTab] = useState<Tab>("consent");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [consentLedger, setConsentLedger] = useState<ConsentLedgerRow[]>([]);
  const [consentBusy, setConsentBusy] = useState(false);
  const [grantPrincipal, setGrantPrincipal] = useState("");
  const [grantPurpose, setGrantPurpose] = useState("process documentation and deliverables");
  const [revokePrincipal, setRevokePrincipal] = useState("");
  const [revokePurpose, setRevokePurpose] = useState("process documentation and deliverables");

  const [rights, setRights] = useState<RightsItem[]>([]);
  const [rightsBusy, setRightsBusy] = useState(false);
  const [rightsPrincipal, setRightsPrincipal] = useState("");
  const [rightsType, setRightsType] = useState("access");
  const [rightsDetails, setRightsDetails] = useState("");

  const [incidents, setIncidents] = useState<Record<string, unknown>[]>([]);
  const [incidentsBusy, setIncidentsBusy] = useState(false);
  const [incidentStateFilter, setIncidentStateFilter] = useState("");
  const [incidentUpdates, setIncidentUpdates] = useState<Record<string, { state: string; notes: string }>>({});

  const loadConsentLedger = useCallback(async () => {
    if (!projectId.trim()) return;
    setConsentBusy(true);
    setError(null);
    try {
      const res = await api(`/api/dpdp/${encodeURIComponent(projectId.trim())}/consent-ledger`);
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown; items?: ConsentLedgerRow[] };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Failed to load consent ledger"));
        return;
      }
      setConsentLedger(Array.isArray(data.items) ? data.items : []);
    } finally {
      setConsentBusy(false);
    }
  }, [api, projectId]);

  const loadRights = useCallback(async () => {
    if (!projectId.trim()) return;
    setRightsBusy(true);
    setError(null);
    try {
      const res = await api(`/api/dpdp/rights?project_id=${encodeURIComponent(projectId.trim())}`);
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown; items?: RightsItem[] };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Failed to load rights queue"));
        return;
      }
      setRights(Array.isArray(data.items) ? data.items : []);
    } finally {
      setRightsBusy(false);
    }
  }, [api, projectId]);

  const loadIncidents = useCallback(async () => {
    if (!projectId.trim()) return;
    setIncidentsBusy(true);
    setError(null);
    try {
      const q = incidentStateFilter.trim()
        ? `?state=${encodeURIComponent(incidentStateFilter.trim())}`
        : "";
      const res = await api(`/api/dpdp/${encodeURIComponent(projectId.trim())}/incidents${q}`);
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown; items?: Record<string, unknown>[] };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Failed to load incidents"));
        return;
      }
      setIncidents(Array.isArray(data.items) ? data.items : []);
    } finally {
      setIncidentsBusy(false);
    }
  }, [api, projectId, incidentStateFilter]);

  useEffect(() => {
    if (!projectId.trim()) return;
    if (tab === "consent") void loadConsentLedger();
    if (tab === "rights") void loadRights();
    if (tab === "incidents") void loadIncidents();
  }, [projectId, tab, loadConsentLedger, loadRights, loadIncidents]);

  async function recordConsent(granted: boolean) {
    if (!projectId.trim()) return;
    setMessage(null);
    setError(null);
    const body =
      granted
        ? { principal_id: grantPrincipal.trim(), purpose: grantPurpose.trim() }
        : { principal_id: revokePrincipal.trim(), purpose: revokePurpose.trim() };
    if (!body.principal_id || !body.purpose) {
      setError("Principal and purpose are required.");
      return;
    }
    const path = granted ? "consent" : "consent/revoke";
    const res = await api(`/api/dpdp/${encodeURIComponent(projectId.trim())}/${path}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Consent request failed"));
      return;
    }
    setMessage(granted ? "Consent recorded." : "Revocation recorded.");
    await loadConsentLedger();
  }

  async function enqueueRights() {
    if (!projectId.trim()) return;
    setMessage(null);
    setError(null);
    const res = await api("/api/dpdp/rights", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId.trim(),
        principal_id: rightsPrincipal.trim() || "principal_unknown",
        request_type: rightsType,
        details: rightsDetails.trim() || null,
      }),
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Failed to queue rights request"));
      return;
    }
    setMessage("Rights request queued.");
    await loadRights();
  }

  async function updateIncident(runId: string) {
    if (!projectId.trim() || !runId) return;
    const upd = incidentUpdates[runId] ?? { state: "triaged", notes: "" };
    setError(null);
    setMessage(null);
    const res = await api(
      `/api/dpdp/${encodeURIComponent(projectId.trim())}/incidents/${encodeURIComponent(runId)}/state`,
      {
        method: "POST",
        body: JSON.stringify({ state: upd.state, resolution_notes: upd.notes.trim() || null }),
      }
    );
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Failed to update incident"));
      return;
    }
    setMessage(`Incident ${runId} updated.`);
    await loadIncidents();
  }

  if (!token) {
    return (
      <div className="p-4">
        <p className="text-sm text-[var(--text-muted)]">Sign in to open the DPDP Compliance Centre.</p>
      </div>
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "consent", label: "Consent ledger" },
    { id: "rights", label: "Rights queue" },
    { id: "incidents", label: "Breach incidents" },
    { id: "data", label: "Data & storage" },
  ];

  return (
    <div className="space-y-4 p-2 sm:p-4">
      <div>
        <h1 className="text-2xl font-semibold">DPDP Compliance Centre</h1>
        <p className="text-sm text-[var(--text-muted)]">
          Project-scoped consent, data-subject requests, and breach incident workflow. For project-level shortcuts, use{" "}
          <span className="font-medium">Settings → DPDP</span> from a project.
        </p>
      </div>

      <Card className="space-y-3 p-4">
        <ProjectPicker value={projectId} onChange={setProjectId} />
        <div className="flex flex-wrap gap-2">
          {tabs.map((t) => (
            <Button
              key={t.id}
              type="button"
              variant={tab === t.id ? "primary" : "secondary"}
              className={tab === t.id ? "" : "border-[var(--surface-border-strong)] bg-[var(--surface-default)]"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </Button>
          ))}
        </div>
      </Card>

      {error ? <p className="text-sm text-[var(--error)]">{error}</p> : null}
      {message ? <p className="text-sm text-[var(--success)]">{message}</p> : null}

      {tab === "consent" && projectId ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="space-y-3 p-4">
            <h2 className="text-base font-semibold">Record consent</h2>
            <Input placeholder="Principal ID" value={grantPrincipal} onChange={(e) => setGrantPrincipal(e.target.value)} />
            <Input placeholder="Purpose" value={grantPurpose} onChange={(e) => setGrantPurpose(e.target.value)} />
            <Button type="button" onClick={() => void recordConsent(true)} disabled={consentBusy}>
              Grant consent
            </Button>
          </Card>
          <Card className="space-y-3 p-4">
            <h2 className="text-base font-semibold">Record revocation</h2>
            <Input placeholder="Principal ID" value={revokePrincipal} onChange={(e) => setRevokePrincipal(e.target.value)} />
            <Input placeholder="Purpose" value={revokePurpose} onChange={(e) => setRevokePurpose(e.target.value)} />
            <Button type="button" variant="secondary" onClick={() => void recordConsent(false)} disabled={consentBusy}>
              Revoke consent
            </Button>
          </Card>
          <Card className="p-4 lg:col-span-2">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">Ledger (newest first)</h2>
              <Button type="button" variant="ghost" onClick={() => void loadConsentLedger()} disabled={consentBusy}>
                {consentBusy ? "Loading…" : "Refresh"}
              </Button>
            </div>
            {!consentLedger.length ? (
              <p className="mt-2 text-sm text-[var(--text-caption)]">No ledger entries yet.</p>
            ) : (
              <ul className="mt-3 space-y-2 text-sm">
                {consentLedger.map((row) => (
                  <li key={row.id} className="rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] p-2">
                    <span className={row.granted ? "text-[var(--success)]" : "text-[var(--error)]"}>
                      {row.granted ? "Granted" : "Revoked"}
                    </span>
                    {" · "}
                    <strong>{row.principal_id}</strong> — {row.purpose}
                    <span className="block text-xs text-[var(--text-caption)]">
                      {row.created_at ?? "—"}
                      {row.granted_by ? ` · by ${row.granted_by}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ) : null}

      {tab === "rights" && projectId ? (
        <Card className="space-y-3 p-4">
          <h2 className="text-base font-semibold">Data subject requests</h2>
          <div className="flex flex-wrap gap-2">
            <Input
              className="max-w-xs"
              placeholder="Principal ID"
              value={rightsPrincipal}
              onChange={(e) => setRightsPrincipal(e.target.value)}
            />
            <Select
              className="max-w-xs"
              value={rightsType}
              onChange={(e) => setRightsType(e.target.value)}
            >
              <option value="access">access</option>
              <option value="correction">correction</option>
              <option value="erasure">erasure</option>
            </Select>
          </div>
          <Textarea rows={2} placeholder="Details (optional)" value={rightsDetails} onChange={(e) => setRightsDetails(e.target.value)} />
          <div className="flex gap-2">
            <Button type="button" onClick={() => void enqueueRights()} disabled={rightsBusy}>
              Queue request
            </Button>
            <Button type="button" variant="secondary" onClick={() => void loadRights()} disabled={rightsBusy}>
              Refresh list
            </Button>
          </div>
          <ul className="space-y-2 text-sm">
            {rights.map((item) => (
              <li key={item.id} className="rounded border border-[var(--surface-border)] p-2">
                <strong>{item.id}</strong> — {item.request_type} ({item.status}) — {item.principal_id}
                {item.created_at ? <span className="block text-xs text-[var(--text-caption)]">{item.created_at}</span> : null}
                {item.details ? <span className="block text-[var(--text-muted)]">{item.details}</span> : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {tab === "incidents" && projectId ? (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">Breach notifications</h2>
            <Select
              className="max-w-[220px] w-auto"
              value={incidentStateFilter}
              onChange={(e) => setIncidentStateFilter(e.target.value)}
            >
              <option value="">All states</option>
              {INCIDENT_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            <Button type="button" variant="secondary" onClick={() => void loadIncidents()} disabled={incidentsBusy}>
              {incidentsBusy ? "Loading…" : "Refresh"}
            </Button>
          </div>
          {!incidents.length ? (
            <p className="text-sm text-[var(--text-caption)]">No incidents match this filter.</p>
          ) : (
            <div className="space-y-4">
              {incidents.map((inc) => {
                const runId = String(inc.run_id ?? "");
                const state = String(inc.state ?? "open");
                const upd = incidentUpdates[runId] ?? { state: state || "triaged", notes: "" };
                return (
                  <div
                    key={runId || JSON.stringify(inc)}
                    className="rounded border border-[var(--surface-border-strong)] p-3 text-sm"
                  >
                    <p>
                      <strong>Run</strong>{" "}
                      <code className="rounded bg-[var(--surface-muted)] px-1">{runId}</code> — state{" "}
                      <span className="font-medium">{state}</span>
                    </p>
                    {inc.incident_id ? (
                      <p className="text-2xs text-[var(--text-caption)]">Incident: {String(inc.incident_id)}</p>
                    ) : null}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Select
                        className="min-w-[160px] w-auto text-xs"
                        value={upd.state}
                        onChange={(e) =>
                          setIncidentUpdates((prev) => ({
                            ...prev,
                            [runId]: { ...upd, state: e.target.value },
                          }))
                        }
                      >
                        {INCIDENT_STATES.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </Select>
                      <Input
                        className="min-w-[200px] flex-1 text-xs"
                        placeholder="Resolution notes"
                        value={upd.notes}
                        onChange={(e) =>
                          setIncidentUpdates((prev) => ({
                            ...prev,
                            [runId]: { ...upd, notes: e.target.value },
                          }))
                        }
                      />
                      <Button type="button" variant="secondary" className="text-xs" onClick={() => void updateIncident(runId)} disabled={!runId}>
                        Update state
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      ) : null}

      {tab === "data" ? (
        <Card className="space-y-3 p-4 text-sm text-[var(--text-default)]">
          <h2 className="text-base font-semibold text-[var(--text-default)]">What this deployment stores</h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>Workspace artifacts under each project (runs, generated files, parsed document JSON, LP bookmarks file).</li>
            <li>Operational memory rows and memory events linked to projects and runs.</li>
            <li>DPDP consent ledger and rights-request rows in the database; breach JSON under workspace/dpdp/breaches.</li>
          </ul>
          <p className="text-[var(--text-muted)]">
            Use per-project settings for a compact DPDP view.{" "}
            {projectId ? (
              <Link href={`/projects/${projectId}/settings/dpdp`} className="text-[var(--accent-blue)] underline">
                Open DPDP settings for {projectId}
              </Link>
            ) : (
              "Select a project to link to its settings."
            )}
          </p>
        </Card>
      ) : null}

      {!projectId && tab !== "data" ? (
        <p className="text-sm text-[var(--text-caption)]">Select a project to load this tab.</p>
      ) : null}
    </div>
  );
}
