"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useCreateModel, useModels } from "@/hooks/useModels";
import { FinancialModelWizard } from "@/components/models/FinancialModelWizard";
import { Button } from "@/components/ui/Button";

export default function ModelsPage() {
  const params = useParams();
  const pid = typeof params.pid === "string" ? params.pid : Array.isArray(params.pid) ? params.pid[0] ?? "" : "";
  const [showWizard, setShowWizard] = useState(false);
  const models = useModels(pid);
  const createModel = useCreateModel(pid);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
        <Link href={`/projects/${pid}`} className="hover:text-[var(--text-default)]">Studio</Link>
        <span>/</span>
        <span className="text-[var(--text-default)] font-medium">Models</span>
      </div>
      <h1 className="text-2xl font-semibold">Analytical Models</h1>
      {showWizard ? (
        <FinancialModelWizard
          onComplete={(data) => {
            void createModel.mutateAsync({
              name: data.name,
              assumptions: data.assumptions as Record<string, unknown>,
            }).then(() => setShowWizard(false));
          }}
        />
      ) : (
        <Button type="button" onClick={() => setShowWizard(true)}>
          New model
        </Button>
      )}
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
