"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/apiClient";
import { Button } from "@/components/ui/Button";

export const DOCUMENT_CANVAS_ENABLED =
  process.env.NEXT_PUBLIC_DOCUMENT_CANVAS_ENABLED !== "false";

const ARTIFACT_TABS = [
  { key: "narrative_md", label: "Narrative" },
  { key: "sop_markdown", label: "SOP" },
  { key: "raci_markdown", label: "RACI" },
  { key: "process_map_mermaid", label: "Process Map" },
] as const;

type ArtifactKey = (typeof ARTIFACT_TABS)[number]["key"];

type SaveState = "idle" | "saving" | "saved" | "error";

export function DocumentCanvas({
  artifacts,
  projectId,
  runId,
}: {
  artifacts: Record<string, unknown> | null;
  projectId: string;
  runId: string;
}) {
  const available = ARTIFACT_TABS.filter(
    ({ key }) => typeof artifacts?.[key] === "string" && (artifacts[key] as string).length > 0
  );

  const [activeKey, setActiveKey] = useState<ArtifactKey | null>(null);
  const [edited, setEdited] = useState<string>("");
  const [original, setOriginal] = useState<string>("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [regenNote, setRegenNote] = useState<string | null>(null);

  // When available tabs change (e.g. run finishes), auto-select first
  useEffect(() => {
    if (available.length === 0) return;
    const first = available[0].key;
    if (!activeKey || !available.find((t) => t.key === activeKey)) {
      setActiveKey(first); // eslint-disable-line react-hooks/set-state-in-effect
    }
  }, [available.map((a) => a.key).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load content when tab switches — setState inside effect is intentional here:
  // we need to reset editor content synchronously with the selected tab/artifact.
  useEffect(() => {
    if (!activeKey) return;
    const content = (artifacts?.[activeKey] as string | undefined) ?? "";
    setEdited(content); // eslint-disable-line react-hooks/set-state-in-effect
    setOriginal(content);
    setSaveState("idle");
  }, [activeKey, artifacts]);

  const isDirty = edited !== original;

  const handleSave = async () => {
    if (!activeKey || !isDirty) return;
    // Capture the value being saved before the await so that edits typed
    // during the in-flight request are not silently discarded.
    const snapshot = edited;
    setSaveState("saving");
    try {
      const res = await apiFetch(`/api/runs/${projectId}/${runId}/canvas`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact_key: activeKey, content: snapshot }),
      });
      if (!res.ok) {
        setSaveState("error");
        setTimeout(() => setSaveState("idle"), 4000);
        return;
      }
      const body = (await res.json().catch(() => ({}))) as {
        regenerated?: string[];
        regen_errors?: string[];
      };
      setOriginal(snapshot);
      const regenerated = Array.isArray(body.regenerated) ? body.regenerated : [];
      const regenErrors = Array.isArray(body.regen_errors) ? body.regen_errors : [];
      if (regenerated.length > 0) {
        setRegenNote(`Refreshed ${regenerated.join(", ").toUpperCase()}`);
      } else if (regenErrors.length > 0) {
        setRegenNote("Saved (Office refresh failed)");
      } else {
        setRegenNote(null);
      }
      setSaveState("saved");
      setTimeout(() => {
        setSaveState("idle");
        setRegenNote(null);
      }, 3000);
    } catch {
      setSaveState("error");
      setTimeout(() => setSaveState("idle"), 4000);
    }
  };

  if (available.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-sm text-[var(--text-caption)]">
          No editable text artifacts yet. Canvas becomes available once a run generates narrative,
          SOP, RACI, or process map output.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Artifact tab selector */}
      <div className="flex shrink-0 border-b border-[var(--surface-border)] px-2 pt-1" role="tablist" aria-label="Document artifact tabs">
        {available.map(({ key, label }) => (
          <button
            key={key}
            role="tab"
            id={`canvas-tab-${key}`}
            aria-selected={activeKey === key}
            aria-controls={`canvas-panel-${key}`}
            tabIndex={activeKey === key ? 0 : -1}
            onClick={() => setActiveKey(key)}
            onKeyDown={(e) => {
              const keys = available.map((a) => a.key);
              const idx = keys.indexOf(key);
              if (e.key === "ArrowRight") { e.preventDefault(); setActiveKey(keys[(idx + 1) % keys.length]); }
              else if (e.key === "ArrowLeft") { e.preventDefault(); setActiveKey(keys[(idx - 1 + keys.length) % keys.length]); }
              else if (e.key === "Home") { e.preventDefault(); setActiveKey(keys[0]); }
              else if (e.key === "End") { e.preventDefault(); setActiveKey(keys[keys.length - 1]); }
            }}
            className={[
              "mr-1 rounded-t px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent-blue,#0072B1)]",
              activeKey === key
                ? "bg-[var(--surface-default)] text-[var(--text-default)] border border-b-transparent border-[var(--surface-border)]"
                : "text-[var(--text-caption)] hover:text-[var(--text-default)]",
            ].join(" ")}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Split editor / preview */}
      {activeKey && (
        <div
          id={`canvas-panel-${activeKey}`}
          role="tabpanel"
          aria-labelledby={`canvas-tab-${activeKey}`}
          className="flex min-h-0 flex-1 gap-px bg-[var(--surface-border)]"
        >
          {/* Editor pane */}
          <div className="flex min-w-0 flex-1 flex-col bg-[var(--surface-default)]">
            <p className="shrink-0 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-caption)]">
              Edit
            </p>
            <textarea
              className="min-h-0 flex-1 resize-none bg-transparent p-2 font-mono text-xs text-[var(--text-default)] outline-none"
              value={edited}
              onChange={(e) => {
                setEdited(e.target.value);
                if (saveState === "saved" || saveState === "error") {
                  setSaveState("idle");
                  setRegenNote(null);
                }
              }}
              spellCheck={false}
            />
          </div>

          {/* Preview pane */}
          <div className="flex min-w-0 flex-1 flex-col bg-[var(--surface-muted)]">
            <p className="shrink-0 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-caption)]">
              Preview
            </p>
            <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-2 text-xs text-[var(--text-default)]">
              {edited}
            </pre>
          </div>
        </div>
      )}

      {/* Footer save bar */}
      <div className="flex shrink-0 items-center justify-between border-t border-[var(--surface-border)] px-3 py-2">
        <span role="status" aria-live="polite" aria-atomic="true" className="text-xs">
          {saveState === "saved" && (
            <span className="text-[var(--success,#16a34a)]">
              Saved{regenNote ? ` · ${regenNote}` : ""}
            </span>
          )}
          {saveState === "error" && (
            <span className="text-[var(--error)]">Save failed — try again</span>
          )}
        </span>
        <Button
          onClick={handleSave}
          disabled={!isDirty || saveState === "saving"}
          aria-busy={saveState === "saving"}
          variant="primary"
        >
          {saveState === "saving" ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}
