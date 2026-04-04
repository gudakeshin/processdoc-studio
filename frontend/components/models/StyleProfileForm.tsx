"use client";

import { useState } from "react";

import { Input } from "@/components/ui/Input";

export function StyleProfileForm() {
  const [formality, setFormality] = useState("Formal");
  const [tone, setTone] = useState("Authoritative");
  const [persona, setPersona] = useState("Senior Director");
  const [verbosity, setVerbosity] = useState("Balanced");
  const [audience, setAudience] = useState("C-suite");

  return (
    <div className="grid gap-2 rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4">
      <h3 className="text-base font-semibold">Style Profile</h3>
      <Input value={formality} onChange={(e) => setFormality(e.target.value)} />
      <Input value={tone} onChange={(e) => setTone(e.target.value)} />
      <Input value={persona} onChange={(e) => setPersona(e.target.value)} />
      <Input value={verbosity} onChange={(e) => setVerbosity(e.target.value)} />
      <Input value={audience} onChange={(e) => setAudience(e.target.value)} />
      <p className="text-2xs text-[var(--text-muted)]">
        Resolution: project defaults + user preferences + run override.
      </p>
    </div>
  );
}
