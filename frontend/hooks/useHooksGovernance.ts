"use client";

import { useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import { emitToast } from "@/lib/toast-bus";

/** Loads and manages the run's hook-execution governance list (view + disable-by-name). */
export function useHooksGovernance(pid: string, onError: (message: string) => void) {
  const { api } = useAuth();
  const [hooksBusy, setHooksBusy] = useState(false);
  const [hooksData, setHooksData] = useState<Array<Record<string, unknown>>>([]);

  async function loadHooks() {
    if (!pid || hooksBusy) return;
    setHooksBusy(true);
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/hooks`);
      const data = (await res.json().catch(() => ({}))) as { hooks?: Array<Record<string, unknown>>; detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to load hooks"));
      setHooksData(Array.isArray(data.hooks) ? data.hooks : []);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to load hooks");
    } finally {
      setHooksBusy(false);
    }
  }

  async function disableHookByName(hookName: string, reason: string) {
    if (!pid || !hookName.trim()) return;
    try {
      const res = await api(`/api/runs/${encodeURIComponent(pid)}/hooks/disable`, {
        method: "POST",
        body: JSON.stringify({ hook_name: hookName.trim(), reason: reason.trim() }),
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to disable hook"));
      await loadHooks();
      emitToast({ message: `Hook ${hookName.trim()} disabled`, kind: "success" });
    } catch (e) {
      onError(e instanceof Error ? e.message : "Failed to disable hook");
    }
  }

  return { hooksBusy, hooksData, loadHooks, disableHookByName };
}
