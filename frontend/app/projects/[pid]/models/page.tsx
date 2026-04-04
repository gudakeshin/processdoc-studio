"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useCreateModel, useModels } from "@/hooks/useModels";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";

export default function ModelsPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const [name, setName] = useState("Operational Forecast Model");
  const [description, setDescription] = useState("");
  const models = useModels(pid);
  const createModel = useCreateModel(pid);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Analytical Models</h1>
      <p className="text-sm text-[var(--text-muted)]">Project: {pid}</p>
      <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 space-y-2">
        <h2 className="text-base font-semibold">Create model</h2>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Model name" />
        <Textarea
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description"
        />
        <Button
          type="button"
          onClick={() => void createModel.mutateAsync({ name, description })}
          disabled={createModel.isPending}
        >
          {createModel.isPending ? "Creating..." : "Create model"}
        </Button>
      </div>
      <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4">
        <h2 className="text-base font-semibold">Model list</h2>
        {models.isLoading ? (
          <p className="text-sm text-[var(--text-muted)]">Loading models...</p>
        ) : null}
        <ul className="mt-2 space-y-2 text-sm">
          {(models.data ?? []).map((m) => (
            <li key={m.id} className="rounded border border-[var(--surface-border)] p-2">
              <div className="font-medium">{m.name}</div>
              <div className="text-[var(--text-muted)]">{m.description ?? "-"}</div>
              <div className="text-2xs text-[var(--text-caption)]">Versions: {m.version_count ?? 0}</div>
              <Link href={`/projects/${pid}/models/${m.id}`} className="text-sm">
                Open model editor
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
