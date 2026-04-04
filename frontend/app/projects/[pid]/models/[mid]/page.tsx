"use client";

import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import { useState } from "react";

import { ExcelIntegrationPanel } from "@/components/excel/ExcelIntegrationPanel";
import { ConflictResolutionPanel } from "@/components/excel/ConflictResolutionPanel";
import { StyleProfileForm } from "@/components/models/StyleProfileForm";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ScoreGauge } from "@/components/ui/ScoreGauge";
import { StatusDot } from "@/components/ui/StatusDot";
import { Textarea } from "@/components/ui/Textarea";
import { useCreateScenario, useModelDashboard, useModelDetail, useModelVersions } from "@/hooks/useModels";
import { useModelRealtime } from "@/hooks/useModelRealtime";

const ModelDashboard = dynamic(() => import("@/components/models/ModelDashboard").then((mod) => mod.ModelDashboard), {
  ssr: false,
  loading: () => <p className="text-sm text-[var(--text-muted)]">Loading dashboard...</p>,
});

export default function ModelEditorPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const mid = typeof params.mid === "string" ? params.mid : Array.isArray(params.mid) ? params.mid[0] ?? "" : "";
  const [scenarioName, setScenarioName] = useState("Baseline");
  const [overridesJson, setOverridesJson] = useState('{"growth_rate": 0.1}');
  const detail = useModelDetail(pid, mid);
  const versions = useModelVersions(pid, mid);
  const dashboard = useModelDashboard(pid, mid);
  const createScenario = useCreateScenario(pid, mid);
  const realtime = useModelRealtime(pid, mid);

  async function handleCreateScenario() {
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(overridesJson) as Record<string, unknown>;
    } catch {
      parsed = {};
    }
    await createScenario.mutateAsync({ name: scenarioName, assumption_overrides: parsed });
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Model Editor</h1>
      <p className="text-sm text-[var(--text-muted)]">
        Project: {pid} · Model: {mid}
      </p>
      <p className="text-2xs text-[var(--text-caption)]">
        Realtime: <span className="font-medium">{realtime.connectionState}</span> · last event id: {realtime.lastEventId || "-"}
      </p>
      <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 text-sm">
        <h2 className="mb-2 text-base font-semibold">Model details</h2>
        {detail.isLoading ? (
          <p className="text-[var(--text-muted)]">Loading model...</p>
        ) : (
          <>
            <p>
              <strong>Name:</strong> {detail.data?.model.name ?? "-"}
            </p>
            <p>
              <strong>Description:</strong> {detail.data?.model.description ?? "-"}
            </p>
          </>
        )}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <StyleProfileForm />
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
        <Input
          value={scenarioName}
          onChange={(e) => setScenarioName(e.target.value)}
          placeholder="Scenario name"
        />
        <Textarea
          rows={4}
          value={overridesJson}
          onChange={(e) => setOverridesJson(e.target.value)}
          className="font-mono"
        />
        <Button
          type="button"
          onClick={() => void handleCreateScenario()}
          disabled={createScenario.isPending}
        >
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
      <ConflictResolutionPanel projectId={pid} modelId={mid} />
    </div>
  );
}
