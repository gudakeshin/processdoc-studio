"use client";

import { useEffect, useState } from "react";

import { Input } from "@/components/ui/Input";
import { useStyleProfile, useSaveStyleProfile } from "@/hooks/useModels";

export function StyleProfileForm({ projectId, modelId }: { projectId: string; modelId: string }) {
  const profile = useStyleProfile(projectId, modelId);
  const save = useSaveStyleProfile(projectId, modelId);

  const [formality, setFormality] = useState("Formal");
  const [tone, setTone] = useState("Authoritative");
  const [persona, setPersona] = useState("Senior Director");
  const [verbosity, setVerbosity] = useState("Balanced");
  const [audience, setAudience] = useState("C-suite");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (profile.data) {
      setFormality(profile.data.formality);
      setTone(profile.data.tone);
      setPersona(profile.data.persona);
      setVerbosity(profile.data.verbosity);
      setAudience(profile.data.audience);
    }
  }, [profile.data]);

  async function handleSave() {
    await save.mutateAsync({ formality, tone, persona, verbosity, audience });
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  return (
    <div className="grid gap-2 rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4">
      <h3 className="text-base font-semibold">Style Profile</h3>
      <Input
        aria-label="Formality"
        placeholder="Formality"
        value={formality}
        onChange={(e) => setFormality(e.target.value)}
      />
      <Input
        aria-label="Tone"
        placeholder="Tone"
        value={tone}
        onChange={(e) => setTone(e.target.value)}
      />
      <Input
        aria-label="Persona"
        placeholder="Persona"
        value={persona}
        onChange={(e) => setPersona(e.target.value)}
      />
      <Input
        aria-label="Verbosity"
        placeholder="Verbosity"
        value={verbosity}
        onChange={(e) => setVerbosity(e.target.value)}
      />
      <Input
        aria-label="Audience"
        placeholder="Audience"
        value={audience}
        onChange={(e) => setAudience(e.target.value)}
      />
      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => void handleSave()}
          className="rounded-lg bg-[#86BC24] px-4 py-1.5 text-sm font-medium text-white hover:bg-[#7aa71f] transition disabled:opacity-50"
        >
          {save.isPending ? "Saving..." : "Save"}
        </button>
        {saved && <span className="text-xs text-[#86BC24] font-medium">Saved ✓</span>}
      </div>
      <p className="text-2xs text-[var(--text-muted)]">
        Resolution: project defaults + user preferences + run override.
      </p>
    </div>
  );
}
