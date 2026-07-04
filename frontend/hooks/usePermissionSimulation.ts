"use client";

import { useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";

/** Runs the permission-preflight simulation for a project's plan-ready run. */
export function usePermissionSimulation(
  pid: string,
  selectedOutputTypes: string[],
  planPayload: unknown,
  onError: (message: string) => void
) {
  const { api } = useAuth();
  const [permissionSimBusy, setPermissionSimBusy] = useState(false);
  const [permissionSimResult, setPermissionSimResult] = useState<any | null>(null);

  async function simulatePermissionPreflight() {
    if (!pid || permissionSimBusy) return;
    setPermissionSimBusy(true);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/permission/simulate`, {
        method: "POST",
        body: JSON.stringify({
          run_status: "plan_ready",
          requested_outputs: selectedOutputTypes,
          has_approval: true,
          enforce_policy: false,
          plan_payload: planPayload ?? {},
        }),
      });
      const data = (await res.json().catch(() => ({}))) as any;
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Permission simulation failed"));
      setPermissionSimResult(data);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Permission simulation failed");
    } finally {
      setPermissionSimBusy(false);
    }
  }

  return { permissionSimBusy, permissionSimResult, simulatePermissionPreflight };
}
