"use client";

import { useEffect, useId, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import { Select } from "@/components/ui/Select";

export const ADMIN_LAST_PROJECT_KEY = "admin:lastProjectId";

export type ProjectOption = { id: string; name: string };

type ProjectPickerProps = {
  value: string;
  onChange: (projectId: string) => void;
  className?: string;
};

export function ProjectPicker({ value, onChange, className }: ProjectPickerProps) {
  const { api, token } = useAuth();
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectId = useId();

  useEffect(() => {
    if (!token) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    void api("/api/projects")
      .then(async (res) => {
        const data = (await res.json().catch(() => ({}))) as { items?: ProjectOption[] };
        if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to load projects"));
        setProjects(Array.isArray(data.items) ? data.items : []);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load projects"))
      .finally(() => setLoading(false));
  }, [api, token]);

  useEffect(() => {
    if (!projects.length || value) return;
    const stored =
      typeof window !== "undefined" ? window.sessionStorage.getItem(ADMIN_LAST_PROJECT_KEY) : null;
    const next =
      stored && projects.some((p) => p.id === stored) ? stored : projects[0]?.id ?? "";
    if (next) {
      window.sessionStorage.setItem(ADMIN_LAST_PROJECT_KEY, next);
      onChange(next);
    }
  }, [projects, value, onChange]);

  return (
    <div className={className}>
      <label htmlFor={selectId} className="mb-1 block text-xs font-medium text-[var(--text-caption)]">Project</label>
      <Select
        id={selectId}
        className="w-full max-w-xl"
        value={value}
        disabled={loading || !projects.length}
        onChange={(e) => {
          const id = e.target.value;
          if (typeof window !== "undefined") {
            window.sessionStorage.setItem(ADMIN_LAST_PROJECT_KEY, id);
          }
          onChange(id);
        }}
      >
        {!projects.length ? (
          <option value="">{loading ? "Loading projects…" : "No projects yet — create one first"}</option>
        ) : null}
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} · {p.id}
          </option>
        ))}
      </Select>
      {error ? <p className="mt-1 text-xs text-[var(--error)]">{error}</p> : null}
    </div>
  );
}
