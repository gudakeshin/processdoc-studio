"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useCreateProjectMutation, useDeleteProjectMutation, useProjectsQuery } from "@/hooks/useProjects";
import { useAuth } from "@/lib/auth-context";
import { Skeleton } from "@/components/ui/Skeleton";

export default function ProjectsIndexPage() {
  const router = useRouter();
  const { token, ready, logout } = useAuth();
  const [hydrated, setHydrated] = useState(false);
  const [name, setName] = useState("My engagement");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);
  const projects = useProjectsQuery(Boolean(token));
  const createProjectMutation = useCreateProjectMutation();
  const deleteProjectMutation = useDeleteProjectMutation();
  const didRedirectRef = useRef(false);
  const lastActiveElRef = useRef<HTMLElement | null>(null);

  const filtered = useMemo(
    () => {
      const items = projects.data ?? [];
      return items.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()) || p.id.includes(query));
    },
    [projects.data, query]
  );

  useEffect(() => {
    // Hydration guard to keep server/client initial markup identical.
     
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      if (didRedirectRef.current) return;
      didRedirectRef.current = true;
      router.replace("/login?next=/projects");
    }
  }, [ready, token, router]);

  async function handleCreateProject() {
    setError(null);
    try {
      const id = await createProjectMutation.mutateAsync(name);
      router.push(`/projects/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }

  function requestDeleteProject(projectId: string, projectName: string) {
    lastActiveElRef.current = document.activeElement as HTMLElement | null;
    setError(null);
    setPendingDelete({ id: projectId, name: projectName });
    setDeleteConfirmOpen(true);
  }

  function closeDeleteDialog() {
    setDeleteConfirmOpen(false);
    setPendingDelete(null);
    lastActiveElRef.current?.focus?.();
  }

  async function confirmDeleteProject() {
    if (!pendingDelete) return;
    const { id, name: projectName } = pendingDelete;
    setError(null);
    setDeletingProjectId(id);
    let ok = false;
    try {
      await deleteProjectMutation.mutateAsync(id);
      ok = true;
    } catch (e) {
      setError(e instanceof Error ? e.message : `Delete failed for "${projectName}".`);
    } finally {
      setDeletingProjectId(null);
      if (ok) closeDeleteDialog();
    }
  }

  if (!hydrated || !ready || !token) {
    return (
      <main style={{ padding: 24 }}>
        <p>Redirecting…</p>
      </main>
    );
  }

  const onDeleteDialogKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      closeDeleteDialog();
      return;
    }
    if (e.key !== "Tab") return;

    const root = e.currentTarget;
    const focusable = Array.from(
      root.querySelectorAll<HTMLElement>(
        'button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])'
      )
    ).filter((el) => !el.hasAttribute("disabled") && el.tabIndex !== -1);

    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement | null;

    if (e.shiftKey) {
      if (!active || active === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  return (
    <main className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">My Projects</h1>
        <Button variant="ghost" type="button" onClick={logout}>
          Sign out
        </Button>
      </header>

      <section className="grid gap-3 rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 shadow-sm md:grid-cols-[1fr_auto_auto] md:items-end">
        <label className="grid gap-2 text-sm">
          New project name
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <Button type="button" onClick={() => void handleCreateProject()} disabled={createProjectMutation.isPending}>
          {createProjectMutation.isPending ? "Creating..." : "Create & Open"}
        </Button>
        <Link href="/projects/new" className="text-sm">
          Open 3-step wizard
        </Link>
      </section>

      {error ? <p className="text-sm text-[var(--error)]">{error}</p> : null}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">Projects</h2>
          <Input className="max-w-sm" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search projects..." />
        </div>
        {projects.isPending ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy>
            {[0, 1, 2].map((i) => (
              <Card key={i} className="min-h-[170px] space-y-3 p-4">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-1/2" />
                <Skeleton className="mt-4 h-8 w-28" />
              </Card>
            ))}
          </div>
        ) : null}
        {filtered.length === 0 && !projects.isPending ? <p className="text-sm text-[var(--primary-700)]">No projects yet.</p> : null}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {!projects.isPending
            ? filtered.map((p) => (
            <Card key={p.id} className="min-h-[170px] space-y-2">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-base font-semibold">{p.name}</h3>
                <Badge>Owner</Badge>
              </div>
              <p className="text-xs text-[var(--primary-700)]">Project ID: {p.id}</p>
              <p className="text-xs text-[var(--primary-700)]">Last run: --</p>
              <div className="flex items-center justify-between gap-3 pt-2 text-sm">
                <Link href={`/projects/${p.id}`}>Open project</Link>
                <Button
                  type="button"
                  variant="ghost"
                  className="text-[var(--error)] hover:bg-[color:color-mix(in_srgb,var(--error)_10%,transparent)]"
                  disabled={deletingProjectId === p.id}
                  onClick={() => requestDeleteProject(p.id, p.name)}
                >
                  {deletingProjectId === p.id ? "Deleting..." : "Delete"}
                </Button>
              </div>
            </Card>
              ))
            : null}
        </div>
      </section>

      {deleteConfirmOpen && pendingDelete ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-project-title"
            aria-describedby="delete-project-desc"
            className="w-full max-w-md rounded-lg border border-[color:color-mix(in_srgb,var(--error)_35%,transparent)] bg-[var(--surface-default)] p-4 shadow-lg"
            tabIndex={-1}
            onKeyDown={onDeleteDialogKeyDown}
          >
            <h2 id="delete-project-title" className="text-lg font-semibold">
              Delete project?
            </h2>
            <p id="delete-project-desc" className="mt-2 text-sm text-[var(--text-muted)]">
              This will permanently delete{" "}
              <span className="font-medium text-[var(--text-default)]">{pendingDelete.name}</span>. This cannot be undone.
            </p>
            {error ? <p className="mt-3 text-sm text-[var(--error)]">{error}</p> : null}
            <div className="mt-4 flex items-center justify-end gap-2">
              <Button type="button" variant="secondary" autoFocus onClick={closeDeleteDialog}>
                Cancel
              </Button>
              <Button
                type="button"
                variant="secondary"
                className="border border-[var(--error)] text-[var(--error)] hover:bg-[color:color-mix(in_srgb,var(--error)_10%,transparent)]"
                disabled={deletingProjectId === pendingDelete.id}
                onClick={() => void confirmDeleteProject()}
              >
                {deletingProjectId === pendingDelete.id ? "Deleting..." : "Delete"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
