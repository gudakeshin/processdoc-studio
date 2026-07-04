"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import { useState } from "react";

import { ExcelIntegrationPanel } from "@/components/excel/ExcelIntegrationPanel";
import { ConflictResolutionPanel } from "@/components/excel/ConflictResolutionPanel";
import { EnhancedConflictResolution } from "@/components/excel/EnhancedConflictResolution";
import { AuditLogViewer } from "@/components/excel/AuditLogViewer";
import { CollaborativeEditingLocks } from "@/components/excel/CollaborativeEditingLocks";
import { ConsolidatedFinancialDashboard } from "@/components/models/ConsolidatedFinancialDashboard";
import { FinancialReportGenerator } from "@/components/models/FinancialReportGenerator";
import { StyleProfileForm } from "@/components/models/StyleProfileForm";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ScoreGauge } from "@/components/ui/ScoreGauge";
import { StatusDot } from "@/components/ui/StatusDot";
import { getApiBase } from "@/lib/api";
import { emitToast } from "@/lib/toast-bus";
import {
  useAuditLog,
  useBatchResolveConflicts,
  useConflictDetail,
  useConsolidatedFinancial,
  useCreateScenario,
  useGenerateReport,
  useModelConflicts,
  useModelDashboard,
  useModelDetail,
  useModelVersions,
  useResolveModelConflict,
} from "@/hooks/useModels";
import { useCollaborativeLocks } from "@/hooks/useCollaborativeLocks";
import { useModelRealtime } from "@/hooks/useModelRealtime";

const ModelDashboard = dynamic(() => import("@/components/models/ModelDashboard").then((mod) => mod.ModelDashboard), {
  ssr: false,
  loading: () => <p className="text-sm text-[var(--text-muted)]">Loading dashboard...</p>,
});

type Tab = "overview" | "financial" | "conflicts" | "audit" | "reports" | "collaboration";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "financial", label: "Financial Overview" },
  { id: "conflicts", label: "Conflict Resolution" },
  { id: "audit", label: "Audit" },
  { id: "reports", label: "Reports" },
  { id: "collaboration", label: "Collaboration" },
];

type ScenarioPair = { key: string; value: string };

export default function ModelEditorPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const mid = typeof params.mid === "string" ? params.mid : Array.isArray(params.mid) ? params.mid[0] ?? "" : "";

  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [scenarioName, setScenarioName] = useState("Baseline");
  const [scenarioPairs, setScenarioPairs] = useState<ScenarioPair[]>([{ key: "growth_rate", value: "0.1" }]);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null);
  const [showAdvancedConflicts, setShowAdvancedConflicts] = useState(false);

  // Audit log server-side filters
  const [auditFilters, setAuditFilters] = useState<{ event_type?: string; cell_ref?: string; offset: number }>({ offset: 0 });

  const detail = useModelDetail(pid, mid);
  const versions = useModelVersions(pid, mid);
  const dashboard = useModelDashboard(pid, mid);
  const createScenario = useCreateScenario(pid, mid);
  const realtime = useModelRealtime(pid, mid);

  // Tab: financial
  const consolidated = useConsolidatedFinancial(pid, mid);

  // Tab: conflicts
  const conflicts = useModelConflicts(pid, mid);
  const conflictDetail = useConflictDetail(pid, mid, selectedConflictId);
  const resolveConflict = useResolveModelConflict(pid, mid);
  const batchResolve = useBatchResolveConflicts(pid, mid);

  // Tab: audit
  const auditLog = useAuditLog(pid, mid, auditFilters);
  const [auditAllEvents, setAuditAllEvents] = useState<import("@/components/excel/AuditLogViewer").AuditEvent[]>([]);

  // Accumulate events for "load more"
  if (auditLog.data && auditFilters.offset === 0 && auditAllEvents.length === 0 && auditLog.data.events.length > 0) {
    setAuditAllEvents(auditLog.data.events);
  }

  // Tab: reports
  const generateReport = useGenerateReport(pid, mid);

  // Tab: collaboration
  const collab = useCollaborativeLocks(pid, mid);

  function addScenarioPair() {
    setScenarioPairs([...scenarioPairs, { key: "", value: "" }]);
  }

  function updateScenarioPair(idx: number, field: "key" | "value", val: string) {
    setScenarioPairs(scenarioPairs.map((p, i) => i === idx ? { ...p, [field]: val } : p));
  }

  function removeScenarioPair(idx: number) {
    setScenarioPairs(scenarioPairs.filter((_, i) => i !== idx));
  }

  async function handleCreateScenario() {
    setScenarioError(null);
    for (const pair of scenarioPairs) {
      if (!pair.key.trim()) {
        setScenarioError("All keys must be non-empty.");
        return;
      }
      if (isNaN(Number(pair.value))) {
        setScenarioError(`Value for "${pair.key}" must be a number.`);
        return;
      }
    }
    const overrides: Record<string, number> = {};
    for (const pair of scenarioPairs) {
      overrides[pair.key.trim()] = Number(pair.value);
    }
    await createScenario.mutateAsync({ name: scenarioName, assumption_overrides: overrides });
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2 text-sm text-[var(--text-muted)] mb-1">
          <Link href={`/projects/${pid}`} className="hover:text-[var(--text-default)]">Studio</Link>
          <span>/</span>
          <Link href={`/projects/${pid}/models`} className="hover:text-[var(--text-default)]">Models</Link>
          <span>/</span>
          <span className="text-[var(--text-default)] font-medium">{detail.data?.model.name ?? mid}</span>
        </div>
        <h1 className="text-2xl font-semibold">{detail.data?.model.name ?? "Model Editor"}</h1>
        <p className="text-2xs text-[var(--text-caption)]">
          Realtime: <span className="font-medium">{realtime.connectionState}</span> · last event: {realtime.lastEventId || "-"}
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 overflow-x-auto border-b border-[var(--surface-border)]">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setActiveTab(t.id)}
            className={[
              "shrink-0 px-3 py-2 text-sm font-medium border-b-2 transition-colors",
              activeTab === t.id
                ? "border-[var(--accent)] text-[var(--text-default)]"
                : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-default)]",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: Overview */}
      {activeTab === "overview" && (
        <div className="space-y-4">
          <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 text-sm">
            <h2 className="mb-2 text-base font-semibold">Model details</h2>
            {detail.isLoading ? (
              <p className="text-[var(--text-muted)]">Loading model...</p>
            ) : (
              <>
                <p><strong>Name:</strong> {detail.data?.model.name ?? "-"}</p>
                <p><strong>Description:</strong> {detail.data?.model.description ?? "-"}</p>
              </>
            )}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <StyleProfileForm projectId={pid} modelId={mid} />
            <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 text-sm text-[var(--text-default)]">
              <h3 className="mb-2 text-base font-semibold">Behavioral Learning Nudge</h3>
              <p className="mb-3">You have changed tone in 7 of your last 10 runs. Save as a new default?</p>
              <div className="flex items-center gap-2 text-sm">
                <StatusDot status="warn" describedBy="learning-nudge-advisory" />
                <span id="learning-nudge-advisory">Advisory recommendation</span>
              </div>
              <div className="mt-3">
                <ScoreGauge score={0.82} />
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 space-y-2">
            <h2 className="text-base font-semibold">Scenario management</h2>
            <Input value={scenarioName} onChange={(e) => setScenarioName(e.target.value)} placeholder="Scenario name" />
            <div className="space-y-2">
              {scenarioPairs.map((pair, idx) => (
                <div key={idx} className="flex gap-2 items-center">
                  <Input
                    placeholder="Key"
                    value={pair.key}
                    onChange={(e) => updateScenarioPair(idx, "key", e.target.value)}
                    className="flex-1"
                  />
                  <Input
                    placeholder="Value (number)"
                    value={pair.value}
                    onChange={(e) => updateScenarioPair(idx, "value", e.target.value)}
                    className="flex-1"
                  />
                  <button
                    type="button"
                    onClick={() => removeScenarioPair(idx)}
                    className="text-xs text-red-500 hover:text-red-700 px-1"
                    aria-label="Remove field"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={addScenarioPair}
                className="text-xs text-[#86BC24] hover:underline"
              >
                + Add field
              </button>
            </div>
            {scenarioError && <p className="text-xs text-red-500">{scenarioError}</p>}
            <Button type="button" onClick={() => void handleCreateScenario()} disabled={createScenario.isPending}>
              {createScenario.isPending ? "Saving..." : "Create scenario"}
            </Button>
            <ul className="space-y-1 text-2xs text-[var(--text-muted)]">
              {(detail.data?.scenarios ?? []).map((scenario) => (
                <li key={scenario.id}>
                  {scenario.name} ({Object.keys(scenario.assumption_overrides ?? {}).length} overrides)
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4">
            <h2 className="mb-2 text-base font-semibold">Version timeline</h2>
            <ul className="space-y-1 text-sm">
              {(versions.data ?? []).map((version) => (
                <li key={version.version_id}>
                  {version.version_id} - {version.reason} - {version.created_at}
                </li>
              ))}
            </ul>
          </div>
          <ModelDashboard data={dashboard.data} />
          <ExcelIntegrationPanel projectId={pid} modelId={mid} />
        </div>
      )}

      {/* Tab: Financial Overview */}
      {activeTab === "financial" && (
        <div>
          {consolidated.isLoading ? (
            <p className="text-sm text-[var(--text-muted)]">Loading financial data...</p>
          ) : consolidated.error ? (
            <p className="text-sm text-red-500">Failed to load financial data.</p>
          ) : (
            <ConsolidatedFinancialDashboard
              metrics={consolidated.data?.metrics}
              statements={consolidated.data?.statements}
              variances={consolidated.data?.variances ?? []}
              forecasts={consolidated.data?.forecasts ?? []}
              assumptions={consolidated.data?.assumptions}
              dataSource={consolidated.data?.data_source}
            />
          )}
        </div>
      )}

      {/* Tab: Conflict Resolution */}
      {activeTab === "conflicts" && (
        <div className="space-y-4">
          <ConflictResolutionPanel projectId={pid} modelId={mid} />
          <details
            open={showAdvancedConflicts}
            onToggle={(e) => setShowAdvancedConflicts((e.target as HTMLDetailsElement).open)}
            className="rounded-lg border border-[var(--surface-border)]"
          >
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[var(--text-muted)] hover:text-[var(--text-default)] select-none">
              Advanced conflict analysis {showAdvancedConflicts ? "▲" : "▼"}
            </summary>
            <div className="p-4">
              <EnhancedConflictResolution
                conflicts={conflicts.data}
                selectedConflictId={selectedConflictId}
                selectedConflictDetail={conflictDetail.data ?? null}
                onSelectConflict={setSelectedConflictId}
                onResolve={(conflictId, chosenSide) => {
                  void resolveConflict.mutate({ conflictId, chosen_side: chosenSide as "local" | "remote" | "policy" });
                }}
                onBatchResolve={(strategy) => {
                  const openIds = (conflicts.data ?? []).filter((c) => c.status === "open").map((c) => c.id);
                  const chosenSide = strategy === "all" ? "policy" : strategy === "computed" ? "remote" : "local";
                  void batchResolve.mutate({ conflictIds: openIds, chosen_side: chosenSide });
                }}
              />
            </div>
          </details>
        </div>
      )}

      {/* Tab: Audit */}
      {activeTab === "audit" && (
        <AuditLogViewer
          events={auditAllEvents.length > 0 ? auditAllEvents : (auditLog.data?.events ?? [])}
          total={auditLog.data?.total}
          hasMore={auditLog.data?.hasMore}
          onLoadMore={() => {
            const nextOffset = auditFilters.offset + 200;
            const newEvents = auditLog.data?.events ?? [];
            setAuditAllEvents((prev) => [...prev, ...newEvents]);
            setAuditFilters((f) => ({ ...f, offset: nextOffset }));
          }}
          onFilterChange={(filters) => {
            setAuditAllEvents([]);
            setAuditFilters({ ...filters, offset: 0 });
          }}
          onExport={(events, format) => {
            if (format === "csv") {
              const headers = ["id", "timestamp", "eventType", "user", "modelId", "cellRef", "severity"];
              const rows = events.map((e) => headers.map((h) => String((e as Record<string, unknown>)[h] ?? "")).join(","));
              const blob = new Blob([headers.join(",") + "\n" + rows.join("\n")], { type: "text/csv" });
              window.open(URL.createObjectURL(blob));
            } else if (format === "json") {
              const blob = new Blob([JSON.stringify(events, null, 2)], { type: "application/json" });
              window.open(URL.createObjectURL(blob));
            } else {
              // PDF: render a printable table and let the browser "Save as PDF".
              const headers = ["id", "timestamp", "eventType", "user", "modelId", "cellRef", "severity"];
              const esc = (v: unknown) =>
                String(v ?? "").replace(/[&<>]/g, (c) => (c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"));
              const head = headers.map((h) => `<th>${h}</th>`).join("");
              const rows = events
                .map((e) => `<tr>${headers.map((h) => `<td>${esc((e as Record<string, unknown>)[h])}</td>`).join("")}</tr>`)
                .join("");
              const html =
                `<!doctype html><meta charset="utf-8"><title>Audit Log</title>` +
                `<style>body{font-family:sans-serif;padding:24px}table{border-collapse:collapse;width:100%}` +
                `th,td{border:1px solid #ccc;padding:6px 8px;font-size:12px;text-align:left}th{background:#f3f4f6}</style>` +
                `<h2>Audit Log</h2><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
              const win = window.open("", "_blank");
              if (win) {
                win.document.write(html);
                win.document.close();
                win.focus();
                win.print();
              }
            }
          }}
        />
      )}

      {/* Tab: Reports */}
      {activeTab === "reports" && (
        <FinancialReportGenerator
          isLoading={generateReport.isPending}
          onGenerate={(config) => {
            void generateReport.mutateAsync(config).then((result) => {
              if (result.download_path) {
                window.open(`${getApiBase()}${result.download_path}`);
              }
              if (config.recipients.trim()) {
                if (result.emailed) {
                  emitToast({ kind: "success", message: `Report emailed to ${config.recipients}` });
                } else if (result.email_reason === "email_not_configured") {
                  emitToast({ kind: "info", message: "Email is not configured — report downloaded instead" });
                } else {
                  emitToast({ kind: "error", message: "Report generated, but email delivery failed — downloaded instead" });
                }
              }
            });
          }}
        />
      )}

      {/* Tab: Collaboration */}
      {activeTab === "collaboration" && (
        <CollaborativeEditingLocks
          locks={collab.locks}
          presence={collab.presence.map((p) => ({
            userId: p.email,
            userName: p.email,
            lastSeen: p.connectedAt,
            currentCell: p.cursor ?? undefined,
            isActive: true,
          }))}
          conflicts={collab.locks.filter((l) => l.status === "conflicted").map((l) => ({
            cellRef: l.cellRef,
            conflictingUser: l.lockedBy,
            yourVersion: 0,
            theirVersion: l.version,
            timestamp: l.lockedAt,
          }))}
          onRetry={collab.onRetry}
          onForceRelease={collab.onForceRelease}
        />
      )}
    </div>
  );
}
