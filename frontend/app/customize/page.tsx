"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { ProjectPicker } from "@/components/admin/ProjectPicker";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Textarea";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";

type SkillRow = {
  id?: string;
  display_name?: string;
  domain?: string;
  version?: string;
  custom?: boolean;
  output_types?: string[];
  description?: string;
  prompt_instructions?: string;
};

type OutputTypeRow = {
  output_type_id?: string;
  display_name?: string;
  required_skills?: string[];
};

export default function CustomizePage() {
  const { api, token } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [outputTypes, setOutputTypes] = useState<OutputTypeRow[]>([]);
  const [domainFilter, setDomainFilter] = useState("");
  const [customOnly, setCustomOnly] = useState(false);
  const [skillsBusy, setSkillsBusy] = useState(false);
  const [formatsBusy, setFormatsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [expandedSkillId, setExpandedSkillId] = useState<string | null>(null);
  const [companionFiles, setCompanionFiles] = useState<Record<string, string[]>>({});
  const [companionBusy, setCompanionBusy] = useState<string | null>(null);

  const [skillJson, setSkillJson] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [validationErrors, setValidationErrors] = useState<string[] | null>(null);

  const domains = useMemo(() => {
    const d = new Set<string>();
    for (const s of skills) {
      if (s.domain) d.add(String(s.domain));
    }
    return [...d].sort();
  }, [skills]);

  const loadSkills = useCallback(async () => {
    if (!projectId.trim()) return;
    setSkillsBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (domainFilter.trim()) params.set("domain", domainFilter.trim());
      if (customOnly) params.set("custom", "true");
      const qs = params.toString();
      const res = await api(`/api/workspace/${encodeURIComponent(projectId.trim())}/skills${qs ? `?${qs}` : ""}`);
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown; items?: SkillRow[] };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Failed to load skills"));
        return;
      }
      setSkills(Array.isArray(data.items) ? data.items : []);
    } finally {
      setSkillsBusy(false);
    }
  }, [api, projectId, domainFilter, customOnly]);

  const loadOutputTypes = useCallback(async () => {
    if (!projectId.trim()) return;
    setFormatsBusy(true);
    setError(null);
    try {
      const res = await api(`/api/workspace/${encodeURIComponent(projectId.trim())}/output-types`);
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown; items?: OutputTypeRow[] };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Failed to load output types"));
        return;
      }
      setOutputTypes(Array.isArray(data.items) ? data.items : []);
    } finally {
      setFormatsBusy(false);
    }
  }, [api, projectId]);

  useEffect(() => {
    void loadSkills();
  }, [loadSkills]);

  useEffect(() => {
    void loadOutputTypes();
  }, [loadOutputTypes]);

  async function loadCompanions(sid: string) {
    if (!projectId.trim()) return;
    setCompanionBusy(sid);
    setError(null);
    try {
      const res = await api(`/api/workspace/${encodeURIComponent(projectId.trim())}/skills/${encodeURIComponent(sid)}/companions`);
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown; files?: string[] };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Failed to load companions"));
        return;
      }
      setCompanionFiles((prev) => ({ ...prev, [sid]: Array.isArray(data.files) ? data.files : [] }));
    } finally {
      setCompanionBusy(null);
    }
  }

  async function uploadCustomSkill() {
    if (!projectId.trim()) return;
    setUploadBusy(true);
    setMessage(null);
    setError(null);
    setValidationErrors(null);
    try {
      const fd = new FormData();
      fd.append("skill_md", skillJson);
      const res = await api(`/api/workspace/${encodeURIComponent(projectId.trim())}/skills`, {
        method: "POST",
        body: fd,
      });
      const data = (await res.json().catch(() => ({}))) as {
        detail?: unknown;
        status?: string;
        errors?: string[];
        skill_id?: string;
        version?: string;
      };
      if (data.status === "validation_failed") {
        setValidationErrors(Array.isArray(data.errors) ? data.errors : ["Validation failed"]);
        return;
      }
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Upload failed"));
        return;
      }
      setMessage(`Saved custom skill ${data.skill_id ?? ""} v${data.version ?? ""}.`);
      setSkillJson("");
      await loadSkills();
    } finally {
      setUploadBusy(false);
    }
  }

  async function deleteCustomSkill(sid: string) {
    if (!projectId.trim()) return;
    if (!window.confirm(`Delete custom skill "${sid}" from this workspace?`)) return;
    setError(null);
    const res = await api(`/api/workspace/${encodeURIComponent(projectId.trim())}/skills/${encodeURIComponent(sid)}`, {
      method: "DELETE",
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown; status?: string };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Delete failed"));
      return;
    }
    setMessage(`Skill ${sid}: ${data.status ?? "ok"}`);
    await loadSkills();
  }

  if (!token) {
    return (
      <div className="p-4">
        <p className="text-sm text-slate-600">Sign in to customize skills and output types.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-2 sm:p-4">
      <div>
        <h1 className="text-2xl font-semibold">Customize</h1>
        <p className="text-sm text-slate-600">
          Inspect built-in skills, upload custom skills as SKILL.md (YAML frontmatter + markdown body) per project workspace, and review output-type → skill routing.
        </p>
      </div>

      <Card className="space-y-3 p-4">
        <ProjectPicker value={projectId} onChange={setProjectId} />
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Domain filter</label>
            <select
              className="rounded border border-slate-200 px-2 py-2 text-sm"
              value={domainFilter}
              onChange={(e) => setDomainFilter(e.target.value)}
              disabled={!projectId}
            >
              <option value="">All domains</option>
              {domains.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={customOnly}
              onChange={(e) => setCustomOnly(e.target.checked)}
              disabled={!projectId}
            />
            Custom skills only
          </label>
          <Button type="button" variant="secondary" onClick={() => void loadSkills()} disabled={!projectId || skillsBusy}>
            {skillsBusy ? "Loading…" : "Refresh skills"}
          </Button>
          <Button type="button" variant="secondary" onClick={() => void loadOutputTypes()} disabled={!projectId || formatsBusy}>
            {formatsBusy ? "Loading…" : "Refresh output types"}
          </Button>
        </div>
      </Card>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      {message ? <p className="text-sm text-emerald-800">{message}</p> : null}

      <Card className="p-4">
        <h2 className="text-base font-semibold">Skills</h2>
        {!projectId ? (
          <p className="mt-2 text-sm text-slate-500">Select a project.</p>
        ) : !skills.length ? (
          <p className="mt-2 text-sm text-slate-500">No skills match filters.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b text-xs text-slate-600">
                <tr>
                  <th className="py-2 pr-3">ID</th>
                  <th className="py-2 pr-3">Name</th>
                  <th className="py-2 pr-3">Domain</th>
                  <th className="py-2 pr-3">Version</th>
                  <th className="py-2 pr-3">Scope</th>
                  <th className="py-2 pr-3">Outputs</th>
                  <th className="py-2 pr-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {skills.map((s) => {
                  const sid = String(s.id ?? "");
                  const outs = Array.isArray(s.output_types) ? s.output_types.join(", ") : "—";
                  const isCustom = Boolean(s.custom);
                  const open = expandedSkillId === sid;
                  return (
                    <Fragment key={sid}>
                      <tr className="border-b border-slate-100">
                        <td className="py-2 pr-3 font-mono text-xs">{sid}</td>
                        <td className="py-2 pr-3">{s.display_name ?? "—"}</td>
                        <td className="py-2 pr-3">{s.domain ?? "—"}</td>
                        <td className="py-2 pr-3">{s.version ?? "—"}</td>
                        <td className="py-2 pr-3">{isCustom ? <span className="text-violet-700">custom</span> : "built-in"}</td>
                        <td className="max-w-[200px] truncate py-2 pr-3 text-xs" title={outs}>
                          {outs}
                        </td>
                        <td className="py-2 pr-3">
                          <div className="flex flex-wrap gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              className="px-2 py-1 text-xs"
                              onClick={() => setExpandedSkillId(open ? null : sid)}
                            >
                              {open ? "Hide" : "Detail"}
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              className="px-2 py-1 text-xs"
                              onClick={() => void loadCompanions(sid)}
                              disabled={companionBusy === sid}
                            >
                              {companionBusy === sid ? "…" : "Companions"}
                            </Button>
                            {isCustom ? (
                              <Button
                                type="button"
                                variant="ghost"
                                className="px-2 py-1 text-xs text-red-700"
                                onClick={() => void deleteCustomSkill(sid)}
                              >
                                Delete
                              </Button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                      {open ? (
                        <tr className="bg-slate-50">
                          <td colSpan={7} className="px-3 py-3 text-xs text-slate-700">
                            <p className="font-medium text-slate-900">Description</p>
                            <p className="mt-1 whitespace-pre-wrap">{s.description ?? "—"}</p>
                            <p className="mt-2 font-medium text-slate-900">Prompt instructions (preview)</p>
                            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white p-2 font-mono text-[11px]">
                              {(s.prompt_instructions ?? "").slice(0, 1200)}
                              {(s.prompt_instructions?.length ?? 0) > 1200 ? "…" : ""}
                            </pre>
                            {companionFiles[sid]?.length ? (
                              <p className="mt-2 text-slate-600">
                                <span className="font-medium">Companion files:</span> {companionFiles[sid].join(", ")}
                              </p>
                            ) : null}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="p-4">
        <h2 className="text-base font-semibold">Output types</h2>
        {!projectId ? (
          <p className="mt-2 text-sm text-slate-500">Select a project.</p>
        ) : !outputTypes.length ? (
          <p className="mt-2 text-sm text-slate-500">No output types loaded.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b text-xs text-slate-600">
                <tr>
                  <th className="py-2 pr-3">ID</th>
                  <th className="py-2 pr-3">Display name</th>
                  <th className="py-2 pr-3">Required skills</th>
                </tr>
              </thead>
              <tbody>
                {outputTypes.map((o) => {
                  const rs = Array.isArray(o.required_skills) ? o.required_skills : [];
                  return (
                    <tr key={String(o.output_type_id)} className="border-b border-slate-100">
                      <td className="py-2 pr-3 font-mono text-xs">{o.output_type_id}</td>
                      <td className="py-2 pr-3">{o.display_name}</td>
                      <td className="py-2 pr-3 text-xs">
                        {rs.length} ({rs.join(", ")})
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <h2 className="text-base font-semibold">Upload custom skill</h2>
        <p className="text-xs text-slate-600">
          Paste a SKILL.md file: YAML frontmatter with id, domain, display_name, output_types, tools, version, description, sample_instruction, etc., and markdown body for prompt instructions (Cursor/Claude style). JSON upload is still accepted if you send skill_json from API clients.
        </p>
        <Textarea
          rows={12}
          className="font-mono text-xs"
          placeholder="---\nid: my_skill_v1\n...\n---\n\n## Instructions\n..."
          value={skillJson}
          onChange={(e) => setSkillJson(e.target.value)}
          disabled={!projectId}
        />
        {validationErrors?.length ? (
          <ul className="list-disc pl-5 text-xs text-red-700">
            {validationErrors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        ) : null}
        <Button type="button" onClick={() => void uploadCustomSkill()} disabled={!projectId || !skillJson.trim() || uploadBusy}>
          {uploadBusy ? "Validating…" : "Upload skill"}
        </Button>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        <Card className="space-y-2 p-4 text-sm text-slate-700">
          <h3 className="font-semibold text-slate-900">Plugin marketplace</h3>
          <p className="text-slate-600">Not connected — this is a local-first deployment. Future work: signed plugin bundles and version pinning.</p>
          <ul className="list-disc space-y-1 pl-5 text-xs">
            <li>No remote catalog configured</li>
            <li>Custom skills are the supported extension point today</li>
          </ul>
        </Card>
        <Card className="space-y-2 p-4 text-sm text-slate-700">
          <h3 className="font-semibold text-slate-900">Connector access</h3>
          <p className="text-slate-600">Not connected — document ingestion uses uploaded files and workspace storage only.</p>
          <ul className="list-disc space-y-1 pl-5 text-xs">
            <li>No SharePoint/Drive/Graph OAuth in this build</li>
            <li>Use project upload + parsed JSON pipeline</li>
          </ul>
        </Card>
      </div>

      {projectId ? (
        <p className="text-xs text-slate-500">
          <Link href={`/projects/${projectId}`} className="text-blue-700 underline">
            Open project {projectId}
          </Link>
        </p>
      ) : null}
    </div>
  );
}
