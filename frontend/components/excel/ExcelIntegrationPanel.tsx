import { useState } from "react";

import { extractApiErrorMessage, parseResponseBodyLoose } from "@/lib/api-error";
import { useAuth } from "@/lib/auth-context";

export function ExcelIntegrationPanel({ projectId, modelId }: { projectId: string; modelId: string }) {
  const { api } = useAuth();
  const [message, setMessage] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function importWorkbook(file: File) {
    setBusy(true);
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await api(
        `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/excel/import`,
        { method: "POST", body: form, headers: {} }
      );
      const { data: parsed, rawText } = await parseResponseBodyLoose(res);
      const data = (parsed && typeof parsed === "object" ? parsed : {}) as {
        detail?: string;
        status?: string;
        filename?: string;
      };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, rawText || "Import failed"));
      setMessage(`Imported workbook: ${data.filename ?? "file"}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  async function runAction(action: "export" | "sync") {
    setBusy(true);
    setMessage("");
    try {
      const endpoint =
        action === "export"
          ? `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/excel/export`
          : `/api/projects/${encodeURIComponent(projectId)}/models/${encodeURIComponent(modelId)}/excel/sync`;
      const res = await api(endpoint, { method: "POST" });
      const { data: parsed, rawText } = await parseResponseBodyLoose(res);
      const data = (parsed && typeof parsed === "object" ? parsed : {}) as { detail?: string; status?: string; file?: string };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, rawText || `${action} failed`));
      setMessage(action === "export" ? `Export created: ${data.file ?? "export file"}` : "Sync completed");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${action} failed`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 space-y-3 shadow-sm">
      <h3 className="text-base font-semibold">Excel Integration</h3>
      <p className="text-sm text-[var(--primary-700)]">Import workbook data, export model outputs, and run sync with conflict policy.</p>
      <label className="block text-sm">
        <span className="mb-1 block">Import workbook</span>
        <input
          type="file"
          accept=".xlsx,.xls,.csv"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void importWorkbook(file);
          }}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] bg-white px-3 py-2 text-sm text-[var(--primary-900)] hover:bg-[var(--primary-50)]"
          onClick={() => void runAction("export")}
        >
          Export workbook
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-md bg-[var(--accent-blue)] px-3 py-2 text-sm text-white hover:bg-[var(--accent-indigo)]"
          onClick={() => void runAction("sync")}
        >
          Run sync
        </button>
      </div>
      <p className="text-xs text-[var(--primary-600)]">
        Conflict policy: assumption cells = last-write-wins, computed cells = ProcessDoc wins.
      </p>
      {message ? <p className="text-sm">{message}</p> : null}
    </div>
  );
}
