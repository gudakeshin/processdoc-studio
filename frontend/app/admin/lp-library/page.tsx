"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { ProjectPicker } from "@/components/admin/ProjectPicker";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";

type LPItem = {
  id: string;
  path: string;
  heading: string;
  text: string;
  relevance_score: number;
};

type BookmarkRow = { item_id: string; note?: string; added_by?: string };

const SNIPPET_PREVIEW = 400;

export default function LPLibraryPage() {
  const { api, token } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<LPItem[]>([]);
  const [bookmarks, setBookmarks] = useState<BookmarkRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [bookmarksBusy, setBookmarksBusy] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [bookmarkNote, setBookmarkNote] = useState("");

  const headingById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const it of items) {
      m[it.id] = it.heading || "(untitled section)";
    }
    return m;
  }, [items]);

  const search = useCallback(async () => {
    if (!projectId.trim() || !query.trim()) return;
    setError(null);
    setSearchBusy(true);
    try {
      const res = await api(
        `/api/lp-library/search?project_id=${encodeURIComponent(projectId.trim())}&q=${encodeURIComponent(query.trim())}`
      );
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown; items?: LPItem[] };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "LP search failed"));
        return;
      }
      setItems(Array.isArray(data.items) ? data.items : []);
    } finally {
      setSearchBusy(false);
    }
  }, [api, projectId, query]);

  const refreshIndex = useCallback(async () => {
    if (!projectId.trim()) return;
    setError(null);
    setRefreshBusy(true);
    try {
      const res = await api(`/api/lp-library/refresh?project_id=${encodeURIComponent(projectId.trim())}`, {
        method: "POST",
      });
      const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Index refresh failed"));
        return;
      }
      await search();
    } finally {
      setRefreshBusy(false);
    }
  }, [api, projectId, search]);

  const loadBookmarks = useCallback(async () => {
    if (!projectId.trim()) return;
    setError(null);
    setBookmarksBusy(true);
    try {
      const res = await api(`/api/lp-library/bookmarks?project_id=${encodeURIComponent(projectId.trim())}`);
      const data = (await res.json().catch(() => ({}))) as {
        detail?: unknown;
        items?: BookmarkRow[];
      };
      if (!res.ok) {
        setError(extractApiErrorMessage(data, "Bookmarks load failed"));
        return;
      }
      setBookmarks(Array.isArray(data.items) ? data.items : []);
    } finally {
      setBookmarksBusy(false);
    }
  }, [api, projectId]);

  async function bookmark(itemId: string) {
    if (!projectId.trim()) return;
    setError(null);
    const res = await api("/api/lp-library/bookmarks", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId.trim(),
        item_id: itemId,
        note: bookmarkNote.trim(),
      }),
    });
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Bookmark failed"));
      return;
    }
    setBookmarkNote("");
    await loadBookmarks();
  }

  async function removeBookmark(itemId: string) {
    if (!projectId.trim()) return;
    setError(null);
    const res = await api(
      `/api/lp-library/bookmarks/${encodeURIComponent(itemId)}?project_id=${encodeURIComponent(projectId.trim())}`,
      { method: "DELETE" }
    );
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    if (!res.ok) {
      setError(extractApiErrorMessage(data, "Bookmark delete failed"));
      return;
    }
    await loadBookmarks();
  }

  if (!token) {
    return (
      <main className="space-y-4 p-4">
        <p className="text-sm text-[var(--text-muted)]">Sign in to use the LP Library.</p>
      </main>
    );
  }

  return (
    <main className="space-y-4 p-2 sm:p-4">
      <div>
        <h2 className="text-2xl font-semibold">LP Library Browser</h2>
        <p className="text-sm text-[var(--text-muted)]">
          Search indexed leading practices for a project and bookmark snippets. Titles for bookmarks resolve when the item
          appears in your latest search results.
        </p>
      </div>

      <Card className="space-y-3 p-4">
        <ProjectPicker value={projectId} onChange={setProjectId} />
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[240px] flex-1">
            <label className="mb-1 block text-xs font-medium text-[var(--text-caption)]">Query</label>
            <Input
              placeholder="Search LP snippets"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={!projectId}
            />
          </div>
          <Button type="button" onClick={() => void search()} disabled={!projectId || !query.trim() || searchBusy}>
            {searchBusy ? "Searching…" : "Search"}
          </Button>
          <Button type="button" variant="secondary" onClick={() => void refreshIndex()} disabled={!projectId || refreshBusy}>
            {refreshBusy ? "Refreshing…" : "Refresh index"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void loadBookmarks()}
            disabled={!projectId || bookmarksBusy}
          >
            {bookmarksBusy ? "Loading…" : "Load bookmarks"}
          </Button>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--text-caption)]">
            Optional note for next bookmark
          </label>
          <Textarea
            rows={2}
            placeholder="e.g. Use for stakeholder comms tone"
            value={bookmarkNote}
            onChange={(e) => setBookmarkNote(e.target.value)}
            disabled={!projectId}
          />
        </div>
      </Card>

      {error ? <p className="text-sm text-[var(--error)]">{error}</p> : null}

      <section>
        <h3 className="text-lg font-semibold">Results</h3>
        {!items.length ? (
          <p className="mt-2 text-sm text-[var(--text-caption)]">Run a search to see snippets.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {items.map((it) => {
              const isOpen = Boolean(expanded[it.id]);
              const long = it.text.length > SNIPPET_PREVIEW;
              const shown = isOpen || !long ? it.text : `${it.text.slice(0, SNIPPET_PREVIEW)}…`;
              return (
                <li key={it.id} className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-3">
                  <p className="font-medium text-[var(--text-default)]">{it.heading || "(untitled section)"}</p>
                  <p className="text-xs text-[var(--text-caption)]">
                    {it.path} · score {it.relevance_score.toFixed(2)} · id{" "}
                    <code className="rounded bg-[var(--surface-muted)] px-1">{it.id}</code>
                  </p>
                  <p className="my-2 whitespace-pre-wrap text-sm text-[var(--text-muted)]">{shown}</p>
                  <div className="flex flex-wrap gap-2">
                    {long ? (
                      <Button type="button" variant="ghost" className="text-xs" onClick={() => setExpanded((e) => ({ ...e, [it.id]: !isOpen }))}>
                        {isOpen ? "Show less" : "Show full text"}
                      </Button>
                    ) : null}
                    <Button type="button" variant="secondary" onClick={() => void bookmark(it.id)} disabled={!projectId}>
                      Bookmark
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-lg font-semibold">Bookmarks</h3>
        {!bookmarks.length ? (
          <p className="mt-2 text-sm text-[var(--text-caption)]">No bookmarks loaded yet.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {bookmarks.map((b) => (
              <li key={b.item_id} className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-3 text-sm">
                <p className="font-medium text-[var(--text-default)]">{headingById[b.item_id] ?? `Snippet ${b.item_id}`}</p>
                <p className="text-xs text-[var(--text-caption)]">
                  <code className="rounded bg-[var(--surface-muted)] px-1">{b.item_id}</code>
                  {b.added_by ? ` · saved by ${b.added_by}` : null}
                </p>
                {b.note ? <p className="mt-1 text-[var(--text-muted)]">{b.note}</p> : null}
                <Button
                  type="button"
                  variant="ghost"
                  className="mt-2 text-[var(--error)]"
                  onClick={() => void removeBookmark(b.item_id)}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {projectId ? (
        <p className="text-xs text-[var(--text-caption)]">
          Open project:{" "}
          <Link href={`/projects/${projectId}`} className="text-[var(--accent-blue)] underline">
            {projectId}
          </Link>
        </p>
      ) : null}
    </main>
  );
}
