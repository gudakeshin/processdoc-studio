"use client";

import { useCallback, useEffect, useState } from "react";
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

  // When available tabs change (e.g. run finishes), auto-select first
  useEffect(() => {
    if (available.length === 0) return;
    const first = available[0].key;
    if (!activeKey || !available.find((t) => t.key === activeKey)) {
      setActiveKey(first);
    }
  }, [available.map((a) => a.key).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load content when tab switches
  useEffect(() => {
    if (!activeKey) return;
    const content = (artifacts?.[activeKey] as string | undefined) ?? "";
    setEdited(content);
    setOriginal(content);
    setSaveState("idle");
  }, [activeKey, artifacts]);

  const isDirty = edited !== original;

  const handleSave = useCallback(async () => {
    if (!activeKey || !isDirty) return;
    setSaveState("saving");
    try {
      const res = await apiFetch(`/api/runs/${projectId}/${runId}/canvas`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact_key: activeKey, content: edited }),
      });
      if (!res.ok) {
        setSaveState("error");
        return;
      }
      setOriginal(edited);
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch {
      setSaveState("error");
    }
  }, [activeKey, edited, isDirty, projectId, runId]);

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
      <div className="flex shrink-0 border-b border-[var(--surface-border)] px-2 pt-1">
        {available.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveKey(key)}
            className={[
              "mr-1 rounded-t px-3 py-1.5 text-xs font-medium transition-colors",
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
        <div className="flex min-h-0 flex-1 gap-px bg-[var(--surface-border)]">
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
                if (saveState === "saved" || saveState === "error") setSaveState("idle");
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
        {saveState === "saved" && (
          <span className="text-xs text-[var(--success,#16a34a)]">Saved</span>
        )}
        {saveState === "error" && (
          <span className="text-xs text-[var(--error)]">Save failed — try again</span>
        )}
        {(saveState === "idle" || saveState === "saving") && <span />}
        <Button
          onClick={handleSave}
          disabled={!isDirty || saveState === "saving"}
          variant="primary"
        >
          {saveState === "saving" ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}
