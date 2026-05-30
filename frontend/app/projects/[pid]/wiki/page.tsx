"use client";
import { useAuth } from '@/lib/auth-context';

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import dynamic from "next/dynamic";

import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";

// Lazy-load heavy wiki panel components so only the active panel ships in the initial bundle.
const WikiPage = dynamic(() => import("@/components/wiki/WikiPage").then(m => ({ default: m.WikiPage })), {
  loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div>,
});
const WikiQuery = dynamic(() => import("@/components/wiki/WikiQuery").then(m => ({ default: m.WikiQuery })), {
  loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div>,
});
const WikiIngest = dynamic(() => import("@/components/wiki/WikiIngest").then(m => ({ default: m.WikiIngest })), {
  loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div>,
});
const WikiLint = dynamic(() => import("@/components/wiki/WikiLint").then(m => ({ default: m.WikiLint })), {
  loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div>,
});
const WikiSynthesis = dynamic(
  () => import("@/components/wiki/WikiSynthesis").then((m) => ({ default: m.WikiSynthesis })),
  { loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div> },
);
const WikiSchemaAnalysis = dynamic(
  () => import("@/components/wiki/WikiSchemaAnalysis").then((m) => ({ default: m.WikiSchemaAnalysis })),
  { loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div> },
);
const WikiSchemaEditor = dynamic(() => import("@/components/wiki/WikiSchemaEditor"), {
  loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div>,
});
const WikiRefreshScheduler = dynamic(
  () => import("@/components/wiki/WikiRefreshScheduler").then((m) => ({ default: m.WikiRefreshScheduler })),
  { loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div> },
);
const WikiGraph = dynamic(
  () => import("@/components/wiki/WikiGraph").then((m) => ({ default: m.WikiGraph })),
  { loading: () => <div className="p-6 text-sm text-gray-400">Loading graph…</div> },
);
const WikiDashboard = dynamic(
  () => import("@/components/wiki/WikiDashboard").then((m) => ({ default: m.WikiDashboard })),
  { loading: () => <div className="p-6 text-sm text-gray-400">Loading…</div> },
);

type WikiLevel = "project" | "leading_practice";
type RightPanel = "page" | "query" | "ingest" | "health" | "graph" | "schema" | "refresh";

interface PageSummary {
  id: string;
  title: string;
  category: string;
  confidence: string;
  updated_at: string;
  summary?: string;
}

const CONFIDENCE_DOT: Record<string, string> = {
  high:   "bg-green-400",
  medium: "bg-yellow-400",
  low:    "bg-red-400",
};

// Human-readable labels for category keys
const CATEGORY_LABEL: Record<string, string> = {
  document:     "Documents",
  reference:    "References",
  note:         "Notes",
  artifact:     "Data & Analysis",
  run_artifact: "Run Outputs",
  conversation: "Conversations",
};

// Group pages by category for the sidebar
function groupByCategory(pages: PageSummary[]): Record<string, PageSummary[]> {
  return pages.reduce<Record<string, PageSummary[]>>((acc, p) => {
    const cat = p.category || "artifact";
    (acc[cat] ??= []).push(p);
    return acc;
  }, {});
}

// Shorten a title for sidebar display — strips leading org name prefix, caps at 38 chars
function sidebarTitle(title: string): string {
  // Strip repeated leading org names like "Varroc Engineering Limited - "
  const stripped = title.replace(/^varroc\s+engineering\s+(limited\s*[-–]\s*)?/i, "").trim();
  const t = stripped || title;
  return t.length > 38 ? t.slice(0, 36).trimEnd() + "…" : t;
}

export default function WikiPageRoute() {
  const { api } = useAuth();
  const params = useParams();
  const pid =
    typeof params.pid === "string" ? params.pid
    : Array.isArray(params.pid)   ? (params.pid[0] ?? "")
    : "";

  const [wikiLevel, setWikiLevel]       = useState<WikiLevel>("project");
  const [pages, setPages]               = useState<PageSummary[]>([]);
  const [pagesLoading, setPagesLoading] = useState(true);
  const [pagesError, setPagesError]     = useState<string | null>(null);
  const [syncing, setSyncing]           = useState(false);
  const [query, setQuery]               = useState("");
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [rightPanel, setRightPanel]     = useState<RightPanel>("page");
  const searchRef = useRef<HTMLInputElement>(null);

  const projectId = wikiLevel === "project" ? pid : undefined;

  // Sync + load pages. Errors are surfaced to the sidebar instead of silently
  // leaving the prior page list in place.
  const loadPages = useCallback(async (doSync = false) => {
    setPagesLoading(true);
    setPagesError(null);
    try {
      if (doSync && wikiLevel === "project" && pid) {
        setSyncing(true);
        try {
          await api(`/api/wiki/project/sync-documents?project_id=${pid}`, { method: "POST" });
        } catch (err) {
          console.warn("wiki sync-documents failed", err);
        }
        setSyncing(false);
      }
      const params = new URLSearchParams({ limit: "200", sort_by: "updated_at" });
      if (projectId) params.append("project_id", projectId);
      const res = await api(`/api/wiki/${wikiLevel}/pages?${params}`);
      if (!res.ok) {
        setPages([]);
        setPagesError(`Failed to load pages (${res.status})`);
        return;
      }
      const data = await res.json();
      setPages(data.pages ?? []);
    } catch (err) {
      setPages([]);
      setPagesError(err instanceof Error ? err.message : "Failed to load pages");
    } finally {
      setPagesLoading(false);
      setSyncing(false);
    }
  }, [wikiLevel, pid, projectId, api]);

  useEffect(() => {
    setSelectedPageId(null);
    setQuery("");
    void loadPages(true);
  }, [wikiLevel, loadPages]);

  // Filtered pages for sidebar
  const q = query.toLowerCase().trim();
  const filtered = q
    ? pages.filter((p) => p.title.toLowerCase().includes(q) || p.summary?.toLowerCase().includes(q))
    : pages;
  const grouped = groupByCategory(filtered);
  const categories = Object.keys(grouped).sort();

  const handlePageSelect = (id: string) => {
    setSelectedPageId(id);
    setRightPanel("page");
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 h-12 border-b border-[var(--surface-border)] bg-white flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-[var(--text-default)]">Wiki</span>
          {/* Level toggle */}
          <div className="flex border border-[var(--surface-border)]">
            {(["project", "leading_practice"] as WikiLevel[]).map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => setWikiLevel(level)}
                className={`px-3 py-1 text-xs font-medium transition ${
                  wikiLevel === level
                    ? "bg-[var(--text-default)] text-white"
                    : "text-[var(--text-muted)] hover:text-[var(--text-default)]"
                }`}
              >
                {level === "project" ? "Project" : "Leading Practices"}
              </button>
            ))}
          </div>
          {syncing && <span className="text-[10px] text-[var(--text-muted)] animate-pulse">Syncing…</span>}
        </div>

        <div className="flex items-center gap-2">
          {/* Action tabs */}
          {(
            [
              { key: "query",   label: "Ask AI" },
              { key: "ingest",  label: "+ Ingest" },
              { key: "graph",   label: "Graph" },
              { key: "schema",  label: "Schema" },
              { key: "refresh", label: "Refresh" },
              { key: "health",  label: "Health" },
            ] as const
          ).map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => { setRightPanel(key); setSelectedPageId(null); }}
              className={`px-3 py-1 text-xs border transition ${
                rightPanel === key && !selectedPageId
                  ? "border-[var(--accent-blue)] text-[var(--accent-blue)] bg-[var(--surface-muted)]"
                  : "border-[var(--surface-border)] text-[var(--text-muted)] hover:border-[var(--text-default)] hover:text-[var(--text-default)]"
              }`}
            >
              {label}
            </button>
          ))}
          <Link href={`/projects/${pid}`} className="text-xs text-[var(--text-muted)] hover:text-[var(--text-default)] ml-1">
            ← Studio
          </Link>
        </div>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Sidebar ── */}
        <aside className="w-60 flex-shrink-0 border-r border-[var(--surface-border)] flex flex-col bg-[var(--surface-muted)] overflow-hidden">
          {/* Search */}
          <div className="p-2 border-b border-[var(--surface-border)]">
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter pages…"
              className="w-full px-2 py-1.5 text-xs border border-[var(--surface-border)] bg-white text-[var(--text-default)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-blue)]"
            />
          </div>

          {/* Page count + refresh */}
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--surface-border)]">
            <span className="text-[10px] text-[var(--text-muted)]">
              {pages.length} page{pages.length !== 1 ? "s" : ""}
            </span>
            <button
              type="button"
              onClick={() => void loadPages(true)}
              className="text-[10px] text-[var(--accent-blue)] hover:underline disabled:opacity-50"
              disabled={pagesLoading || syncing}
            >
              {syncing ? "syncing…" : "sync"}
            </button>
          </div>

          {/* Page list */}
          <nav className="flex-1 overflow-y-auto overflow-x-hidden py-1">
            {pagesError && !pagesLoading ? (
              <div className="px-3 py-4 space-y-2">
                <p className="text-[10px] text-[var(--error)]">{pagesError}</p>
                <button
                  type="button"
                  onClick={() => void loadPages(false)}
                  className="text-[10px] text-[var(--accent-blue)] hover:underline"
                >
                  Retry
                </button>
              </div>
            ) : pagesLoading ? (
              <div className="space-y-1 p-2">
                {[...Array(6)].map((_, i) => (
                  <Skeleton key={i} className="h-6 w-full" />
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <p className="text-[10px] text-[var(--text-muted)] px-3 py-4 text-center">
                {pages.length === 0 ? "No pages yet. Upload documents in Run Studio." : "No matches."}
              </p>
            ) : (
              categories.map((cat) => (
                <div key={cat}>
                  <div className="px-3 pt-3 pb-1">
                    <span className="text-[9px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
                      {CATEGORY_LABEL[cat] ?? cat}
                    </span>
                  </div>
                  {grouped[cat].map((page) => (
                    <button
                      key={page.id}
                      type="button"
                      onClick={() => handlePageSelect(page.id)}
                      className={`w-full text-left px-3 py-1.5 flex items-center gap-2 overflow-hidden transition group ${
                        selectedPageId === page.id
                          ? "bg-white border-l-2 border-l-[var(--accent-blue)]"
                          : "hover:bg-white/70 border-l-2 border-l-transparent"
                      }`}
                    >
                      <span
                        className={`flex-shrink-0 w-1.5 h-1.5 rounded-full ${CONFIDENCE_DOT[page.confidence] ?? CONFIDENCE_DOT.medium}`}
                      />
                      <span
                        className={`text-xs min-w-0 flex-1 truncate ${
                          selectedPageId === page.id
                            ? "text-[var(--text-default)] font-medium"
                            : "text-[var(--text-muted)] group-hover:text-[var(--text-default)]"
                        }`}
                        title={page.title}
                      >
                        {sidebarTitle(page.title)}
                      </span>
                    </button>
                  ))}
                </div>
              ))
            )}
          </nav>
        </aside>

        {/* ── Main content ── */}
        <main className="flex-1 overflow-y-auto p-6 bg-white">
          {rightPanel === "page" && selectedPageId ? (
            <WikiPage
              wikiType={wikiLevel}
              pageId={selectedPageId}
              projectId={projectId}
              onBack={() => setSelectedPageId(null)}
              onSelectPage={(id) => setSelectedPageId(id)}
            />
          ) : rightPanel === "query" ? (
            <div className="max-w-2xl">
              <h2 className="text-sm font-semibold text-[var(--text-default)] mb-4">Ask the Wiki</h2>
              <WikiQuery wikiType={wikiLevel} projectId={projectId} />
            </div>
          ) : rightPanel === "ingest" ? (
            <div className="max-w-xl">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-[var(--text-default)]">Ingest Source</h2>
                <Button
                  variant="ghost"
                  className="text-xs px-2 py-1"
                  onClick={() => void loadPages(false)}
                >
                  Refresh pages
                </Button>
              </div>
              <WikiIngest wikiType={wikiLevel} projectId={projectId} />
            </div>
          ) : rightPanel === "health" ? (
            <div className="max-w-2xl">
              <h2 className="text-sm font-semibold text-[var(--text-default)] mb-4">Wiki Health</h2>
              <WikiLint wikiType={wikiLevel} projectId={projectId} />
            </div>
          ) : rightPanel === "graph" ? (
            <div className="max-w-4xl">
              <h2 className="text-sm font-semibold text-[var(--text-default)] mb-4">Knowledge Graph</h2>
              <WikiGraph wikiType={wikiLevel} projectId={projectId} />
            </div>
          ) : rightPanel === "schema" ? (
            <div className="max-w-4xl space-y-6">
              <div>
                <h2 className="text-sm font-semibold text-[var(--text-default)] mb-4">Schema Analysis</h2>
                <WikiSchemaAnalysis wikiType={wikiLevel} projectId={projectId} />
              </div>
              <div className="pt-4 border-t border-[var(--surface-border)]">
                <WikiSchemaEditor wikiType={wikiLevel} projectId={projectId} />
              </div>
            </div>
          ) : rightPanel === "refresh" ? (
            <div className="max-w-3xl">
              <h2 className="text-sm font-semibold text-[var(--text-default)] mb-4">Source Refresh</h2>
              <WikiRefreshScheduler wikiType={wikiLevel} projectId={projectId} />
            </div>
          ) : (
            /* Default: no page selected, show landing */
            <div className="max-w-2xl mx-auto pt-12 space-y-6">
              <WikiDashboard wikiType={wikiLevel} projectId={projectId} />
              {pages.length > 0 && (
                <div>
                  <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-2">Recent pages</p>
                  <div className="divide-y divide-[var(--surface-border)] border border-[var(--surface-border)]">
                    {pages.slice(0, 8).map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => handlePageSelect(p.id)}
                        className="w-full text-left px-4 py-2.5 hover:bg-[var(--surface-muted)] transition flex items-center gap-3"
                      >
                        <span className={`flex-shrink-0 w-1.5 h-1.5 rounded-full ${CONFIDENCE_DOT[p.confidence] ?? CONFIDENCE_DOT.medium}`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-[var(--text-default)] truncate">{p.title}</p>
                          {p.summary && (
                            <p className="text-xs text-[var(--text-muted)] truncate mt-0.5">{p.summary}</p>
                          )}
                        </div>
                        <Badge className="flex-shrink-0 text-[10px] capitalize">{p.category}</Badge>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
