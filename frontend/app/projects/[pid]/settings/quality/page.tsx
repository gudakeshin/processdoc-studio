"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useAuth } from "@/lib/auth-context";

export default function SettingsQualityPage() {
  const { api } = useAuth();
  const params = useParams();
  const pid =
    typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const [threshold, setThreshold] = useState("0.8");
  const [maxQaLoops, setMaxQaLoops] = useState("2");
  const [hardGateEnabled, setHardGateEnabled] = useState(true);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!pid.trim()) return;
    void api(`/api/projects/${encodeURIComponent(pid)}/settings`)
      .then(async (res) => {
        const data = (await res.json().catch(() => ({}))) as {
          qa_threshold?: number;
          max_qa_loops?: number;
          hard_gate_enabled?: boolean;
        };
        if (!res.ok) return;
        if (typeof data.qa_threshold === "number") setThreshold(String(data.qa_threshold));
        if (typeof data.max_qa_loops === "number") setMaxQaLoops(String(data.max_qa_loops));
        if (typeof data.hard_gate_enabled === "boolean") setHardGateEnabled(data.hard_gate_enabled);
      })
      .catch(() => {});
  }, [api, pid]);

  async function save() {
    if (!pid.trim()) return;
    const res = await api(`/api/projects/${encodeURIComponent(pid)}/settings`, {
      method: "PUT",
      body: JSON.stringify({
        qa_threshold: Number(threshold),
        max_qa_loops: Number(maxQaLoops),
        hard_gate_enabled: hardGateEnabled,
      }),
    });
    setMessage(res.ok ? "Saved" : "Save failed");
  }

  return (
    <div className="space-y-3 rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 shadow-sm">
      <h2 className="text-lg font-semibold">Quality Settings</h2>
      <p className="text-sm text-[var(--primary-700)]">Set project QA threshold.</p>
      <p className="text-xs text-[var(--primary-600)]">Project: {pid || "unknown"}</p>
      <Input
        value={threshold}
        onChange={(e) => setThreshold(e.target.value)}
        inputMode="decimal"
      />
      <Input
        value={maxQaLoops}
        onChange={(e) => setMaxQaLoops(e.target.value)}
        placeholder="Max QA loops (1-5)"
      />
      <label className="flex items-center gap-2 text-sm">
        <Input
          type="checkbox"
          checked={hardGateEnabled}
          onChange={(e) => setHardGateEnabled(e.target.checked)}
          className="h-4 w-4 p-0"
        />
        Hard gate enabled (block review-ready when evaluator fails)
      </label>
      <Button
        onClick={() => void save()}
      >
        Save threshold
      </Button>
      {message ? <p className="text-sm">{message}</p> : null}
    </div>
  );
}
