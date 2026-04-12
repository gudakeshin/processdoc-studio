"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import {
  WikiDashboard,
  WikiSearch,
  WikiBrowse,
  WikiIngest,
  WikiQuery,
  WikiLint,
} from "@/components/wiki";

type WikiTab = "dashboard" | "search" | "browse" | "ingest" | "query" | "lint";
type WikiLevel = "project" | "leading_practice";

const TABS: { key: WikiTab; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "search", label: "Search" },
  { key: "browse", label: "Browse" },
  { key: "ingest", label: "Ingest" },
  { key: "query", label: "Query" },
  { key: "lint", label: "Health" },
];

export default function WikiPage() {
  const params = useParams();
  const pid =
    typeof params.pid === "string"
      ? params.pid
      : Array.isArray(params.pid)
        ? (params.pid[0] ?? "")
        : "";

  const [activeTab, setActiveTab] = useState<WikiTab>("dashboard");
  const [wikiLevel, setWikiLevel] = useState<WikiLevel>("project");

  return (
    <main className="mx-auto max-w-6xl space-y-4 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Wiki</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Knowledge base for project {pid}
          </p>
        </div>
        <Link
          href={`/projects/${pid}`}
          className="text-xs text-[var(--accent-blue)] hover:underline"
        >
          Back to Project Studio
        </Link>
      </header>

      {/* Wiki Level Toggle */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setWikiLevel("project")}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
            wikiLevel === "project"
              ? "bg-[var(--primary-900)] text-white"
              : "bg-[var(--surface-muted)] text-[var(--text-muted)] hover:bg-[var(--surface-border)]"
          }`}
        >
          Project Wiki
        </button>
        <button
          type="button"
          onClick={() => setWikiLevel("leading_practice")}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
            wikiLevel === "leading_practice"
              ? "bg-[var(--primary-900)] text-white"
              : "bg-[var(--surface-muted)] text-[var(--text-muted)] hover:bg-[var(--surface-border)]"
          }`}
        >
          Leading Practices
        </button>
      </div>

      {/* Tab Navigation */}
      <nav className="flex gap-1 border-b border-[var(--surface-border)]">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-2 text-xs font-medium transition ${
              activeTab === tab.key
                ? "border-b-2 border-[var(--accent-blue)] text-[var(--accent-blue)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-default)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Tab Content */}
      <div>
        {activeTab === "dashboard" && (
          <WikiDashboard wikiType={wikiLevel} projectId={pid} />
        )}
        {activeTab === "search" && (
          <WikiSearch wikiType={wikiLevel} projectId={pid} />
        )}
        {activeTab === "browse" && (
          <WikiBrowse wikiType={wikiLevel} projectId={pid} />
        )}
        {activeTab === "ingest" && (
          <WikiIngest wikiType={wikiLevel} projectId={pid} />
        )}
        {activeTab === "query" && (
          <WikiQuery wikiType={wikiLevel} projectId={pid} />
        )}
        {activeTab === "lint" && (
          <WikiLint wikiType={wikiLevel} projectId={pid} />
        )}
      </div>
    </main>
  );
}
