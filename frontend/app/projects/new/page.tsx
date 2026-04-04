"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useCreateProjectMutation } from "@/hooks/useProjects";

export default function NewProjectPage() {
  const router = useRouter();
  const createProject = useCreateProjectMutation();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("Strategy & Ops");
  const [description, setDescription] = useState("");

  async function finish() {
    const id = await createProject.mutateAsync(name || "New engagement");
    router.push(`/projects/${id}`);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold">New Project Wizard</h1>
      <Card>
        <p className="mb-3 text-sm text-slate-600">Step {step} of 3</p>
        {step === 1 ? (
          <div className="space-y-3">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" />
            <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="Domain" />
          </div>
        ) : null}
        {step === 2 ? (
          <div className="text-sm text-slate-700">Team member invite flow will be added here.</div>
        ) : null}
        {step === 3 ? (
          <textarea
            className="w-full rounded-md border border-slate-300 p-2 text-sm"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            rows={4}
          />
        ) : null}
        <div className="mt-4 flex gap-2">
          <Button variant="secondary" disabled={step === 1} onClick={() => setStep((s) => s - 1)}>
            Back
          </Button>
          {step < 3 ? (
            <Button onClick={() => setStep((s) => s + 1)}>Continue</Button>
          ) : (
            <Button disabled={createProject.isPending} onClick={() => void finish()}>
              {createProject.isPending ? "Creating..." : "Create project"}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
