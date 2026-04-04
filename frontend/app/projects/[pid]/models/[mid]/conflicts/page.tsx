"use client";

import { useParams } from "next/navigation";

import { ConflictResolutionPanel } from "@/components/excel/ConflictResolutionPanel";

export default function ModelConflictsPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const mid = typeof params.mid === "string" ? params.mid : Array.isArray(params.mid) ? params.mid[0] ?? "" : "";

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Model Conflict Center</h1>
      <p className="text-sm text-[var(--text-muted)]">
        Project: {pid} · Model: {mid}
      </p>
      <ConflictResolutionPanel projectId={pid} modelId={mid} />
    </div>
  );
}

