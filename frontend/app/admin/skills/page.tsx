"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { useAuth } from "@/lib/auth-context";

type SkillCard = {
  [key: string]: unknown;
  id: string;
  display_name: string;
  domain: string;
  version?: string;
  custom?: boolean;
  companion_files?: string[];
  source_url?: string;
};

export default function AdminSkillsPage() {
  const { api, token } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [items, setItems] = useState<SkillCard[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedSkillKey, setSelectedSkillKey] = useState<string>("");
  const [editorJson, setEditorJson] = useState("");
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState<"all" | "built_in" | "custom">("all");
  const [companionFiles, setCompanionFiles] = useState<string[]>([]);
  const [selectedCompanionFile, setSelectedCompanionFile] = useState<string>("");
  const [companionContent, setCompanionContent] = useState("");
  const [companionLoading, setCompanionLoading] = useState(false);

  const [skillId, setSkillId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [domain, setDomain] = useState("Strategy & Ops");
  const [outputTypes, setOutputTypes] = useState("narrative");
  const [tools, setTools] = useState("retrieve_context,web_search");
  const [version, setVersion] = useState("1.0.0");
  const [description, setDescription] = useState("");
  const [sampleInstruction, setSampleInstruction] = useState("Create a consulting deliverable.");
  const [promptInstructions, setPromptInstructions] = useState("Generate a compliant, concise output.");

  const selectedSkill = items.find(
    (it) => `${it.id}:${it.version ?? "builtin"}` === selectedSkillKey
  );
  const builtInCount = items.filter((it) => !it.custom).length;
  const customCount = items.filter((it) => !!it.custom).length;
  const filteredItems = items.filter((it) => {
    const inScope =
      scope === "all" || (scope === "custom" ? Boolean(it.custom) : !Boolean(it.custom));
    const needle = search.trim().toLowerCase();
    if (!needle) return inScope;
    return (
      inScope &&
      [it.id, it.display_name, it.domain, it.version ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle)
    );
  });

  async function loadDefaultProject() {
    if (!token || projectId) return;
    const res = await api("/api/projects");
    const data = (await res.json().catch(() => ({}))) as { items?: Array<{ id: string }> };
    const first = Array.isArray(data.items) ? data.items[0] : null;
    if (res.ok && first?.id) setProjectId(first.id);
  }

  async function loadSkills() {
    if (!projectId.trim()) return;
    setError(null);
    const res = await api(`/api/workspace/${encodeURIComponent(projectId)}/skills`);
    const data = (await res.json().catch(() => ({}))) as { detail?: string; items?: SkillCard[] };
    if (!res.ok) {
      setError(typeof data.detail === "string" ? data.detail : "Failed to load skills");
      return;
    }
    const nextItems = Array.isArray(data.items) ? data.items : [];
    setItems(nextItems);
    if (nextItems.length > 0) {
      const selectedExists = nextItems.some(
        (it) => `${it.id}:${it.version ?? "builtin"}` === selectedSkillKey
      );
      const nextSelected = selectedExists
        ? nextItems.find((it) => `${it.id}:${it.version ?? "builtin"}` === selectedSkillKey)
        : nextItems[0];
      if (!nextSelected) {
        return;
      }
      const key = `${nextSelected.id}:${nextSelected.version ?? "builtin"}`;
      setSelectedSkillKey(key);
      setEditorJson(JSON.stringify(nextSelected, null, 2));
      void syncCompanions(nextSelected);
    } else {
      setSelectedSkillKey("");
      setEditorJson("");
      setCompanionFiles([]);
      setSelectedCompanionFile("");
      setCompanionContent("");
    }
  }

  async function loadCompanionFile(skill: SkillCard, filePath: string) {
    if (!projectId.trim()) return;
    setCompanionLoading(true);
    try {
      const q = new URLSearchParams();
      if (skill.version) q.set("version", skill.version);
      q.set("file_path", filePath);
      const res = await api(
        `/api/workspace/${encodeURIComponent(projectId)}/skills/${encodeURIComponent(skill.id)}/companions?${q.toString()}`
      );
      const data = (await res.json().catch(() => ({}))) as { detail?: string; content?: string };
      if (!res.ok) {
        setError(data.detail || "Failed to load companion file");
        setCompanionContent("");
        return;
      }
      setCompanionContent(typeof data.content === "string" ? data.content : "");
    } finally {
      setCompanionLoading(false);
    }
  }

  async function syncCompanions(skill: SkillCard) {
    const files = Array.isArray(skill.companion_files) ? skill.companion_files.filter((x) => typeof x === "string") : [];
    setCompanionFiles(files);
    if (files.length === 0) {
      setSelectedCompanionFile("");
      setCompanionContent("");
      return;
    }
    const first = files[0];
    setSelectedCompanionFile(first);
    await loadCompanionFile(skill, first);
  }

  useEffect(() => {
    if (!token) return;
    void loadDefaultProject();
    if (projectId) void loadSkills();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, projectId]);

  async function saveSkill() {
    if (!projectId.trim() || !selectedSkill) return;
    setError(null);
    setSaveStatus(null);

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(editorJson) as Record<string, unknown>;
    } catch {
      setError("Skill JSON is invalid");
      return;
    }

    const form = new FormData();
    form.append("skill_json", JSON.stringify(parsed));
    if (selectedSkill.version) form.append("version", selectedSkill.version);
    const res = await api(
      `/api/workspace/${encodeURIComponent(projectId)}/skills/${encodeURIComponent(selectedSkill.id)}`,
      {
        method: "PUT",
        body: form,
        headers: {},
      }
    );
    const data = (await res.json().catch(() => ({}))) as {
      detail?: string;
      status?: string;
      errors?: string[];
    };
    if (!res.ok || data.status === "validation_failed") {
      const msg = data.errors?.length ? data.errors.join(", ") : data.detail || "Failed to update skill";
      setError(msg);
      return;
    }
    setSaveStatus("Saved");
    await loadSkills();
  }

  async function createSkill() {
    if (!projectId.trim()) return;
    setError(null);

    const payload = {
      id: skillId,
      domain,
      display_name: displayName,
      output_types: outputTypes.split(",").map((x) => x.trim()).filter(Boolean),
      tools: tools.split(",").map((x) => x.trim()).filter(Boolean),
      prompt_instructions: promptInstructions,
      quality_thresholds: { narrative: 0.8 },
      custom: true,
      version,
      description,
      sample_instruction: sampleInstruction,
    };

    const form = new FormData();
    form.append("skill_json", JSON.stringify(payload));
    const res = await api(`/api/workspace/${encodeURIComponent(projectId)}/skills`, {
      method: "POST",
      body: form,
      headers: {},
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: string; status?: string; errors?: string[] };
    if (!res.ok || data.status === "validation_failed") {
      const msg = data.errors?.length ? data.errors.join(", ") : data.detail || "Failed to create skill";
      setError(msg);
      return;
    }
    await loadSkills();
  }

  async function deleteSkill(id: string) {
    if (!projectId.trim()) return;
    setError(null);
    const res = await api(`/api/workspace/${encodeURIComponent(projectId)}/skills/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const data = (await res.json().catch(() => ({}))) as { detail?: string };
      setError(data.detail || "Delete failed");
      return;
    }
    await loadSkills();
  }

  return (
    <main className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Skills Registry</h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              View, filter, edit, and manage project skills from one workspace.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="secondary" onClick={() => void loadSkills()}>
              Refresh
            </Button>
            <Link href="/admin/skills/new" className="text-sm font-medium text-[var(--text-muted)] underline">
              Open full Skill Wizard
            </Link>
          </div>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-3">
            <p className="text-xs uppercase text-[var(--text-caption)]">Total skills</p>
            <p className="text-xl font-semibold">{items.length}</p>
          </div>
          <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-3">
            <p className="text-xs uppercase text-[var(--text-caption)]">Built-in</p>
            <p className="text-xl font-semibold">{builtInCount}</p>
          </div>
          <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-3">
            <p className="text-xs uppercase text-[var(--text-caption)]">Custom</p>
            <p className="text-xl font-semibold">{customCount}</p>
          </div>
        </div>
      </Card>

      <Card>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="grid gap-2 text-sm">
            Project ID
            <Input value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="p_xxx" />
          </label>
          <label className="grid gap-2 text-sm">
            Search skills
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, id, domain, version"
            />
          </label>
          <label className="grid gap-2 text-sm">
            Scope
            <Select
              value={scope}
              onChange={(e) => setScope(e.target.value as "all" | "built_in" | "custom")}
            >
              <option value="all">All</option>
              <option value="built_in">Built-in</option>
              <option value="custom">Custom</option>
            </Select>
          </label>
        </div>
        {error ? <p className="mt-3 alert alert--error">{error}</p> : null}
        {saveStatus ? <p className="mt-3 rounded-md bg-green-50 p-2 text-sm text-green-700">{saveStatus}</p> : null}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h3 className="text-lg font-semibold">Skill registry</h3>
          <p className="text-sm text-[var(--text-muted)]">Select a skill to inspect and edit its full JSON.</p>
          <ul className="mt-3 space-y-2 text-sm">
            {filteredItems.map((it) => (
              <li
                key={`${it.id}:${it.version ?? "builtin"}`}
                className={`rounded-lg border p-3 transition ${
                  `${it.id}:${it.version ?? "builtin"}` === selectedSkillKey
                    ? "border-[var(--surface-border-strong)] bg-[var(--surface-muted)]"
                    : "border-[var(--surface-border)] bg-[var(--surface-default)] hover:border-[var(--surface-border-strong)]"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium text-[var(--text-default)]">{it.display_name}</p>
                    <p className="text-xs text-[var(--text-muted)]">
                      {it.id} • {it.domain} • {it.version ? `v${it.version}` : "no version"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        it.custom
                          ? "bg-[color-mix(in_srgb,var(--accent-blue)_18%,white)] text-[var(--accent-blue)]"
                          : "bg-[var(--surface-muted)] text-[var(--text-muted)]"
                      }`}
                    >
                      {it.custom ? "custom" : "built-in"}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      className="p-0 text-xs font-medium text-[var(--text-muted)] underline hover:bg-transparent"
                      onClick={() => {
                        const key = `${it.id}:${it.version ?? "builtin"}`;
                        setSelectedSkillKey(key);
                        setEditorJson(JSON.stringify(it, null, 2));
                        setSaveStatus(null);
                        void syncCompanions(it);
                      }}
                    >
                      Open
                    </Button>
                  </div>
                </div>
                {it.custom ? (
                  <div className="mt-2 flex items-center gap-3 text-xs">
                    <Link href={`/admin/skills/${it.id}/edit`} className="underline">
                      Advanced edit
                    </Link>
                    <Button
                      type="button"
                      variant="ghost"
                      className="p-0 text-xs text-[var(--error)] underline hover:bg-transparent"
                      onClick={() => void deleteSkill(it.id)}
                    >
                      Delete
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
          {filteredItems.length === 0 ? (
            <p className="mt-3 rounded-md border border-dashed border-[var(--surface-border)] p-3 text-sm text-[var(--text-muted)]">
              No skills match current filters.
            </p>
          ) : null}
        </Card>

        <Card>
          <h3 className="text-lg font-semibold">Skill JSON editor</h3>
          <p className="text-sm text-[var(--text-muted)]">Review and edit the selected skill payload before saving.</p>
          <Textarea
            value={editorJson}
            onChange={(e) => setEditorJson(e.target.value)}
            rows={22}
            className="mt-2 font-mono text-xs"
            placeholder="Select a skill to view/edit its JSON content"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                try {
                  const parsed = JSON.parse(editorJson) as Record<string, unknown>;
                  setEditorJson(JSON.stringify(parsed, null, 2));
                } catch {
                  setError("Skill JSON is invalid");
                }
              }}
              disabled={!editorJson.trim()}
            >
              Format JSON
            </Button>
            <Button
              type="button"
              onClick={() => void saveSkill()}
              disabled={!selectedSkill || !projectId.trim()}
            >
              Save selected skill
            </Button>
          </div>
        </Card>
      </div>

      <Card>
        <h3 className="text-lg font-semibold">Companion Docs</h3>
        <p className="text-sm text-[var(--text-muted)]">
          Read linked companion guidance for the selected skill.
        </p>
        {selectedSkill?.source_url ? (
          <p className="mt-1 text-xs text-[var(--text-caption)]">
            Source:{" "}
            <a href={selectedSkill.source_url} target="_blank" rel="noreferrer" className="underline">
              {selectedSkill.source_url}
            </a>
          </p>
        ) : null}
        {companionFiles.length > 0 ? (
          <>
            <div className="mt-2 flex flex-wrap gap-2">
              {companionFiles.map((filePath) => (
                <Button
                  key={filePath}
                  type="button"
                  variant="secondary"
                  className={`p-0 px-2 py-1 text-xs ${
                    filePath === selectedCompanionFile
                      ? "border-[var(--surface-border-strong)] bg-[var(--surface-muted)]"
                      : "border-[var(--surface-border)] bg-[var(--surface-default)]"
                  }`}
                  onClick={() => {
                    if (!selectedSkill) return;
                    setSelectedCompanionFile(filePath);
                    void loadCompanionFile(selectedSkill, filePath);
                  }}
                >
                  {filePath.split("/").slice(-2).join("/")}
                </Button>
              ))}
            </div>
            <Textarea
              value={companionLoading ? "Loading..." : companionContent}
              readOnly
              rows={18}
              className="mt-2 font-mono text-xs"
              placeholder="No companion content loaded"
            />
          </>
        ) : (
          <p className="mt-2 rounded-md border border-dashed border-[var(--surface-border)] p-3 text-sm text-[var(--text-muted)]">
            Selected skill has no linked companion files.
          </p>
        )}
      </Card>

      <Card>
        <h3 className="mb-2 text-lg font-semibold">Create skill</h3>
        <p className="text-sm text-[var(--text-muted)]">
          Quick-create a custom skill, or use the full wizard for guided drafting.
        </p>
        <div className="grid gap-2 md:grid-cols-2">
          <Input value={skillId} onChange={(e) => setSkillId(e.target.value)} placeholder="skill id" />
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="display name" />
          <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="domain" />
          <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="version" />
          <Input value={outputTypes} onChange={(e) => setOutputTypes(e.target.value)} placeholder="output types csv" />
          <Input value={tools} onChange={(e) => setTools(e.target.value)} placeholder="tools csv" />
        </div>
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="description"
          rows={2}
          className="mt-2"
        />
        <Textarea
          value={sampleInstruction}
          onChange={(e) => setSampleInstruction(e.target.value)}
          placeholder="sample instruction"
          rows={2}
          className="mt-2"
        />
        <Textarea
          value={promptInstructions}
          onChange={(e) => setPromptInstructions(e.target.value)}
          placeholder="prompt instructions"
          rows={3}
          className="mt-2"
        />
        <Button type="button" onClick={() => void createSkill()} className="mt-2">
          Validate & Save
        </Button>
      </Card>
    </main>
  );
}
