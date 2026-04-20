"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth-context";

export function DocumentUploader({ projectId, autoload = true }: { projectId: string; autoload?: boolean }) {
  const { api, token, ready } = useAuth();
  const [items, setItems] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    if (!projectId || !token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api(`/api/documents/list?project_id=${encodeURIComponent(projectId)}`);
      const data = (await res.json().catch(() => ({}))) as { items?: string[]; detail?: string };
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Failed to load documents");
      }
      setItems(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [api, projectId, token]);

  useEffect(() => {
    if (!autoload || !projectId || !ready || !token) return;
    void loadDocuments();
  }, [projectId, autoload, ready, token, loadDocuments]);

  async function handleUpload(file: File | null) {
    if (!projectId || !file || !token) return;
    setUploading(true);
    setError(null);
    setMessage(null);

    // Capture filename immediately from the File object
    const filename = file.name;

    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("file", file);
      const res = await api("/api/documents/upload", {
        method: "POST",
        body: form,
        headers: {},
      });
      const data = (await res.json().catch(() => ({}))) as {
        filename?: string;
        detail?: string;
      };
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Upload failed");
      }
      setMessage(`Uploaded: ${filename}`);
      await loadDocuments();

      // Ingest document into wiki (non-blocking — wiki page auto-syncs on load too)
      try {
        const params = new URLSearchParams({
          source_type: "document",
          project_id: projectId,
        });
        const wikiRes = await api(`/api/wiki/project/ingest?${params}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_data: { filename } }),
        });
        if (wikiRes.ok) {
          setMessage(`Uploaded: ${filename} — added to wiki`);
        } else {
          setMessage(`Uploaded: ${filename} — wiki sync pending (open Wiki to sync)`);
        }
      } catch {
        setMessage(`Uploaded: ${filename} — wiki sync pending (open Wiki to sync)`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(itemPath: string) {
    if (!projectId || !token) return;
    const filename = itemPath.split("/").pop() ?? itemPath;
    setDeleting(filename);
    setError(null);
    setMessage(null);
    try {
      const res = await api(
        `/api/documents/delete?project_id=${encodeURIComponent(projectId)}&filename=${encodeURIComponent(filename)}`,
        {
          method: "DELETE",
        }
      );
      const data = (await res.json().catch(() => ({}))) as { detail?: string; deleted?: boolean; filename?: string };
      if (!res.ok || !data.deleted) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Delete failed");
      }
      setMessage(`Deleted: ${data.filename ?? filename}`);
      await loadDocuments();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-[var(--surface-border)] bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">Project documents</h3>
        <Button type="button" variant="secondary" onClick={() => void loadDocuments()} disabled={loading || uploading}>
          {loading ? "Refreshing..." : "Refresh"}
        </Button>
      </div>
      <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
        <input
          type="file"
          className="hidden"
          disabled={uploading}
          onChange={(e) => {
            const selected = e.target.files?.[0] ?? null;
            setSelectedFileName(selected?.name ?? null);
            void handleUpload(selected);
            e.currentTarget.value = "";
          }}
        />
        <span className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_35%,transparent)] bg-white px-3 py-2 text-sm text-[var(--primary-900)] hover:bg-[var(--primary-50)]">
          {uploading ? "Uploading..." : "Choose file"}
        </span>
        <span className="text-xs text-[var(--text-muted)]">{selectedFileName ?? "No file selected"}</span>
      </label>
      {uploading ? <p className="text-xs text-[var(--info)]">Uploading document...</p> : null}
      {message ? <p className="text-xs text-[var(--success)]">{message}</p> : null}
      {error ? <p className="text-xs text-[var(--error)]">{error}</p> : null}
      <div className="space-y-2 text-xs text-[var(--text-muted)]">
        {items.length === 0 ? (
          <p>No documents uploaded yet.</p>
        ) : (
          items.map((item) => (
            <div key={item} className="flex items-center justify-between gap-2 rounded border border-[var(--surface-border)] bg-[var(--surface-muted)] px-2 py-1">
              <p className="truncate">{item.split("/").pop() ?? item}</p>
              <Button
                type="button"
                variant="secondary"
                className="px-2 py-1 text-xs"
                disabled={Boolean(deleting)}
                onClick={() => void handleDelete(item)}
              >
                {deleting === (item.split("/").pop() ?? item) ? "Deleting..." : "Delete"}
              </Button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
