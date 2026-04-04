"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useAuth } from "@/lib/auth-context";

type DraftSkill = {
  id: string;
  domain: string;
  display_name: string;
  output_types: string[];
  version: string;
  description: string;
  use_when: string;
  tools: string[];
  prompt_instructions: string;
  workflow_steps: string[];
  feedback_loop: string[];
  freedom_level: "high" | "medium" | "low";
  quality_thresholds: Record<string, number>;
  acceptance_checks: string[];
  default_representation: string;
  sample_instruction: string;
  custom: boolean;
};

export default function NewSkillPage() {
  const { api, token } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const [skillId, setSkillId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [domain, setDomain] = useState("Strategy & Ops");
  const [outputTypesCsv, setOutputTypesCsv] = useState("narrative");
  const [toolsCsv, setToolsCsv] = useState("retrieve_context,memory_lookup,qa_validator");
  const [version, setVersion] = useState("1.0.0");
  const [defaultRepresentation, setDefaultRepresentation] = useState("markdown");
  const [freedomLevel, setFreedomLevel] = useState<"high" | "medium" | "low">("medium");
  const [descriptionWhat, setDescriptionWhat] = useState("");
  const [descriptionWhen, setDescriptionWhen] = useState("");
  const [workflowStepsText, setWorkflowStepsText] = useState("");
  const [feedbackLoopText, setFeedbackLoopText] = useState(
    "Draft output\nRun acceptance checks\nFix issues and regenerate"
  );
  const [acceptanceChecksText, setAcceptanceChecksText] = useState("");
  const [sampleInstruction, setSampleInstruction] = useState("");
  const [qualityThreshold, setQualityThreshold] = useState("0.85");

  const [generatedJson, setGeneratedJson] = useState("");

  async function loadDefaultProject() {
    if (!token || projectId) return;
    const res = await api("/api/projects");
    const data = (await res.json().catch(() => ({}))) as { items?: Array<{ id: string }> };
    const first = Array.isArray(data.items) ? data.items[0] : null;
    if (res.ok && first?.id) setProjectId(first.id);
  }

  useEffect(() => {
    if (!token) return;
    void loadDefaultProject();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const bestPracticeWarnings = useMemo(() => {
    const warnings: string[] = [];
    if (!descriptionWhat.trim() || !descriptionWhen.trim()) {
      warnings.push("Description should include both what the skill does and when to use it.");
    }
    if (/\b(I|you|we)\b/i.test(`${descriptionWhat} ${descriptionWhen}`)) {
      warnings.push("Write description in third person (avoid I/you/we).");
    }
    if ((workflowStepsText.match(/\n/g)?.length ?? 0) < 1) {
      warnings.push("Add a multi-step workflow (at least 2 steps).");
    }
    if (!acceptanceChecksText.trim()) {
      warnings.push("Define explicit acceptance checks.");
    }
    if (!sampleInstruction.trim()) {
      warnings.push("Add a realistic sample instruction.");
    }
    return warnings;
  }, [descriptionWhat, descriptionWhen, workflowStepsText, acceptanceChecksText, sampleInstruction]);

  function buildDraftSkill(): DraftSkill {
    const outputTypes = outputTypesCsv
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    const tools = toolsCsv
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    const workflowSteps = workflowStepsText
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
    const feedbackLoop = feedbackLoopText
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
    const acceptanceChecks = acceptanceChecksText
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);

    const what = descriptionWhat.trim().replace(/\.$/, "");
    const when = descriptionWhen.trim().replace(/\.$/, "");
    const description = `${what}. Use when ${when}.`;

    const promptInstructions =
      `Draft output with ${freedomLevel} freedom. Follow this workflow: ` +
      workflowSteps.map((step, idx) => `${idx + 1}) ${step}`).join(" ") +
      ". Run this feedback loop before finalizing: " +
      feedbackLoop.join(" -> ") +
      ".";

    return {
      id: skillId.trim(),
      domain: domain.trim(),
      display_name: displayName.trim(),
      output_types: outputTypes,
      version: version.trim(),
      description,
      use_when: when,
      tools,
      prompt_instructions: promptInstructions,
      workflow_steps: workflowSteps,
      feedback_loop: feedbackLoop,
      freedom_level: freedomLevel,
      quality_thresholds: {
        [outputTypes[0] || "narrative"]: Number.parseFloat(qualityThreshold) || 0.85,
      },
      acceptance_checks: acceptanceChecks,
      default_representation: defaultRepresentation.trim(),
      sample_instruction: sampleInstruction.trim(),
      custom: true,
    };
  }

  function generateDraft() {
    setError(null);
    setStatus(null);
    const payload = buildDraftSkill();
    setGeneratedJson(JSON.stringify(payload, null, 2));
  }

  async function saveDraft() {
    if (!projectId.trim()) {
      setError("Project ID is required.");
      return;
    }
    setError(null);
    setStatus(null);

    let payloadText = generatedJson;
    if (!payloadText.trim()) {
      payloadText = JSON.stringify(buildDraftSkill());
    }

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(payloadText) as Record<string, unknown>;
    } catch {
      setError("Generated JSON is invalid.");
      return;
    }

    const form = new FormData();
    form.append("skill_json", JSON.stringify(parsed));
    const res = await api(`/api/workspace/${encodeURIComponent(projectId)}/skills`, {
      method: "POST",
      body: form,
      headers: {},
    });
    const data = (await res.json().catch(() => ({}))) as {
      detail?: string;
      status?: string;
      errors?: string[];
    };
    if (!res.ok || data.status === "validation_failed") {
      const msg = data.errors?.length ? data.errors.join(", ") : data.detail || "Failed to create skill";
      setError(msg);
      return;
    }
    setStatus("Skill created successfully.");
  }

  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-semibold">Skill Wizard</h1>
      <p className="text-sm text-[var(--text-muted)]">
        Author skills using structured leading-practice drafting and save directly to the registry.
      </p>
      <Link href="/admin/skills" className="text-sm">
        Back to skills
      </Link>

      <Card>
        <h2 className="text-lg font-semibold">Project and metadata</h2>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <Input value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="project id (p_xxx)" />
          <Input value={skillId} onChange={(e) => setSkillId(e.target.value)} placeholder="skill id (e.g. onboarding_v1)" />
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="display name" />
          <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="domain" />
          <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="version (e.g. 1.0.0)" />
          <Input
            value={defaultRepresentation}
            onChange={(e) => setDefaultRepresentation(e.target.value)}
            placeholder="default representation (markdown/xlsx/drawio_xml)"
          />
        </div>
      </Card>

      <Card>
        <h2 className="text-lg font-semibold">Discovery fields</h2>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <Input value={outputTypesCsv} onChange={(e) => setOutputTypesCsv(e.target.value)} placeholder="output types csv" />
          <Input value={toolsCsv} onChange={(e) => setToolsCsv(e.target.value)} placeholder="tools csv" />
        </div>
        <Textarea
          className="mt-2"
          rows={3}
          value={descriptionWhat}
          onChange={(e) => setDescriptionWhat(e.target.value)}
          placeholder="What this skill does (third-person, concise)."
        />
        <Textarea
          className="mt-2"
          rows={2}
          value={descriptionWhen}
          onChange={(e) => setDescriptionWhen(e.target.value)}
          placeholder="When this skill should be used."
        />
      </Card>

      <Card>
        <h2 className="text-lg font-semibold">Execution design</h2>
        <label className="mt-2 grid max-w-xs gap-2 text-sm">
          Freedom level
          <Select
            value={freedomLevel}
            onChange={(e) => setFreedomLevel(e.target.value as "high" | "medium" | "low")}
          >
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </Select>
        </label>
        <Textarea
          className="mt-2"
          rows={5}
          value={workflowStepsText}
          onChange={(e) => setWorkflowStepsText(e.target.value)}
          placeholder={"Workflow steps, one per line\nRead inputs\nDraft output\nValidate\nFinalize"}
        />
        <Textarea
          className="mt-2"
          rows={4}
          value={feedbackLoopText}
          onChange={(e) => setFeedbackLoopText(e.target.value)}
          placeholder={"Feedback loop, one per line\nDraft output\nRun checks\nFix and rerun"}
        />
        <Textarea
          className="mt-2"
          rows={4}
          value={acceptanceChecksText}
          onChange={(e) => setAcceptanceChecksText(e.target.value)}
          placeholder={"Acceptance checks, one per line\nContains summary section\nIncludes evidence-backed recommendations"}
        />
        <Input
          className="mt-2"
          value={qualityThreshold}
          onChange={(e) => setQualityThreshold(e.target.value)}
          placeholder="quality threshold (e.g. 0.85)"
        />
        <Textarea
          className="mt-2"
          rows={2}
          value={sampleInstruction}
          onChange={(e) => setSampleInstruction(e.target.value)}
          placeholder="Sample instruction for real use case."
        />
      </Card>

      <Card>
        <h2 className="text-lg font-semibold">Best-practice checks</h2>
        {bestPracticeWarnings.length === 0 ? (
          <p className="mt-2 text-sm text-green-700">No warnings. Draft structure looks good.</p>
        ) : (
          <ul className="mt-2 list-disc pl-6 text-sm text-[var(--warning)]">
            {bestPracticeWarnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <h2 className="text-lg font-semibold">Generated skill JSON</h2>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={generateDraft}>
            Generate draft JSON
          </Button>
          <Button type="button" onClick={() => void saveDraft()}>
            Save skill
          </Button>
        </div>
        <Textarea
          className="mt-2 font-mono text-xs"
          rows={18}
          value={generatedJson}
          onChange={(e) => setGeneratedJson(e.target.value)}
          placeholder="Generated JSON appears here. You can edit before saving."
        />
        {error ? <p className="mt-2 text-sm text-[var(--error)]">{error}</p> : null}
        {status ? <p className="mt-2 text-sm text-green-700">{status}</p> : null}
      </Card>
    </main>
  );
}
