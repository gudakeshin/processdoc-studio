"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth-context";

type RightsItem = { id: string; principal_id: string; request_type: string; status: string };

export default function SettingsDpdpPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const { api, token } = useAuth();
  const [rights, setRights] = useState<RightsItem[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    if (!token || !pid) return;
    const rightsRes = await api(`/api/dpdp/rights?project_id=${encodeURIComponent(pid)}`);
    const rightsData = (await rightsRes.json().catch(() => ({}))) as { items?: RightsItem[] };
    setRights(Array.isArray(rightsData.items) ? rightsData.items : []);
    const incidentsRes = await api(`/api/dpdp/${encodeURIComponent(pid)}/incidents`);
    const incidentsData = (await incidentsRes.json().catch(() => ({}))) as { items?: any[] };
    setIncidents(Array.isArray(incidentsData.items) ? incidentsData.items : []);
  }, [api, pid, token]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      void loadAll();
    }, 0);
    return () => window.clearTimeout(t);
  }, [loadAll]);

  async function enqueueAccessRequest() {
    setMessage(null);
    const res = await api("/api/dpdp/rights", {
      method: "POST",
      body: JSON.stringify({
        project_id: pid,
        principal_id: "principal_demo",
        request_type: "access",
        details: "Requested from settings page",
      }),
    });
    if (!res.ok) {
      setMessage("Failed to queue rights request.");
      return;
    }
    setMessage("Rights request queued.");
    await loadAll();
  }

  return (
    <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 text-sm shadow-sm">
      <h2 className="text-base font-semibold">DPDP governance</h2>
      <div className="mt-2 flex gap-2">
        <Button type="button" onClick={() => void enqueueAccessRequest()}>
          Queue sample rights request
        </Button>
        <Button type="button" variant="secondary" onClick={() => void loadAll()}>
          Refresh
        </Button>
      </div>
      {message ? <p className="mt-2 text-xs text-[var(--text-muted)]">{message}</p> : null}
      <h3 className="mt-3 font-medium">Rights queue</h3>
      <ul className="mt-1 space-y-1 text-xs text-[var(--text-muted)]">
        {rights.map((item) => (
          <li key={item.id}>
            {item.id}: {item.request_type} ({item.status})
          </li>
        ))}
      </ul>
      <h3 className="mt-3 font-medium">Incidents</h3>
      <ul className="mt-1 space-y-1 text-xs text-[var(--text-muted)]">
        {incidents.map((item, idx) => (
          <li key={String(item.incident_id ?? item.run_id ?? `incident-${idx}`)}>
            {String(item.incident_id ?? "incident")} - {String(item.state ?? "open")}
          </li>
        ))}
      </ul>
    </div>
  );
}
