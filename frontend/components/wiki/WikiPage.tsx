"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiPage — individual page viewer.
 */

import React, { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { WikiTabNav } from './WikiTabNav';
import { confidenceClass } from '@/utils/wikiColors';

const WikiRelationships = dynamic(
  () => import('./WikiRelationships').then((m) => ({ default: m.WikiRelationships })),
  { loading: () => <div className="p-2 text-xs text-[var(--text-muted)]">Loading relationships…</div> },
);

interface PageLink { id: string; title: string; type: 'inbound' | 'outbound' }

interface PageMetadata {
  id: string;
  title: string;
  category: string;
  confidence: string;
  content: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
  source_memory_ids?: string[];
  source_run_ids?: string[];
  inbound_links: PageLink[];
  outbound_links: PageLink[];
  pages_linking_count: number;
  frontmatter: Record<string, unknown>;
}

interface WikiPageProps {
  wikiType: 'leading_practice' | 'project';
  pageId: string;
  projectId?: string;
  onBack?: () => void;
  /** Called when the user clicks an inbound/outbound link so the parent can change page. */
  onSelectPage?: (pageId: string) => void;
}

export const WikiPage: React.FC<WikiPageProps> = ({ wikiType, pageId, projectId, onBack, onSelectPage }) => {
  const { api } = useAuth();
  const [page, setPage]       = useState<PageMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'content' | 'links' | 'relationships' | 'metadata'>('content');

  useEffect(() => {
    let cancelled = false;
    const fetchPage = async () => {
      try {
        setLoading(true);
        setError(null);
        const params = new URLSearchParams();
        if (projectId) params.append('project_id', projectId);
        const res = await api(`/api/wiki/${wikiType}/pages/${pageId}?${params}`);
        if (!res.ok) throw new Error(res.status === 404 ? 'Page not found' : `Failed to load page (${res.status})`);
        const data = await res.json();
        if (!cancelled) setPage(data.page);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchPage();
    return () => { cancelled = true; };
  }, [wikiType, pageId, projectId, api]);

  if (loading) return (
    <div className="space-y-3">
      <div className="h-5 w-64 bg-[var(--surface-muted)] animate-pulse" />
      <div className="h-3 w-32 bg-[var(--surface-muted)] animate-pulse" />
    </div>
  );

  if (error || !page) return (
    <div className="space-y-3">
      {onBack && (
        <Button variant="ghost" className="text-xs px-2 py-1" onClick={onBack}>
          ← Back
        </Button>
      )}
      <p className="text-xs text-[var(--error)]">{error ?? 'Page not found'}</p>
    </div>
  );

  const renderLinkList = (links: PageLink[], emptyText: string) => {
    if (links.length === 0) {
      return <p className="text-xs text-[var(--text-muted)]">{emptyText}</p>;
    }
    return (
      <div className="space-y-1">
        {links.map((link) => (
          <button
            key={`${link.type}-${link.id}`}
            type="button"
            onClick={() => onSelectPage?.(link.id)}
            disabled={!onSelectPage}
            className="w-full text-left text-xs text-[var(--accent-blue)] py-1 border-b border-[var(--surface-border)] hover:underline disabled:text-[var(--text-muted)] disabled:no-underline"
          >
            {link.title}
          </button>
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Back + Title row */}
      {onBack && (
        <Button variant="ghost" className="text-xs px-2 py-1 -ml-2" onClick={onBack}>
          ← Back
        </Button>
      )}
      <div className="flex items-start justify-between gap-4 pb-3 border-b border-[var(--surface-border)]">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
            <Badge className="capitalize text-[10px]">{page.category}</Badge>
            <span>Updated {new Date(page.updated_at).toLocaleDateString()}</span>
          </div>
          <h1 className="text-xl font-semibold text-[var(--text-default)]">{page.title}</h1>
          <span className={`inline-flex items-center px-2 py-0.5 text-[10px] border capitalize ${confidenceClass[page.confidence] ?? confidenceClass.medium}`}>
            {page.confidence} confidence
          </span>
        </div>

        <div className="flex gap-2 flex-shrink-0 mt-1">
          <Button variant="primary" className="text-xs px-3 py-1.5">Edit</Button>
          {wikiType === 'project' && (
            <Button variant="secondary" className="text-xs px-3 py-1.5">Promote to LP</Button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <WikiTabNav
        tabs={[
          { key: 'content',       label: 'Content' },
          { key: 'links',         label: `Links (${page.inbound_links.length + page.outbound_links.length})` },
          { key: 'relationships', label: 'Relationships' },
          { key: 'metadata',      label: 'Metadata' },
        ]}
        activeTab={activeTab}
        onChange={(k) => setActiveTab(k as typeof activeTab)}
      />

      {/* Content */}
      {activeTab === 'content' && (
        <div className="text-sm text-[var(--text-default)] leading-relaxed whitespace-pre-wrap border-t border-[var(--surface-border)] pt-4">
          {page.content}
        </div>
      )}

      {/* Links */}
      {activeTab === 'links' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
          <div>
            <p className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide mb-2">
              Referenced by ({page.inbound_links.length})
            </p>
            {renderLinkList(page.inbound_links, 'No pages reference this one')}
          </div>
          <div>
            <p className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide mb-2">
              References ({page.outbound_links.length})
            </p>
            {renderLinkList(page.outbound_links, 'No outbound references')}
          </div>
        </div>
      )}

      {/* Relationships */}
      {activeTab === 'relationships' && (
        <div className="pt-2 border-t border-[var(--surface-border)]">
          <WikiRelationships wikiType={wikiType} pageId={page.id} projectId={projectId} />
        </div>
      )}

      {/* Metadata */}
      {activeTab === 'metadata' && (
        <div className="pt-2">
          {Object.keys(page.frontmatter ?? {}).length > 0 ? (
            <dl className="divide-y divide-[var(--surface-border)] border border-[var(--surface-border)]">
              {Object.entries(page.frontmatter).map(([key, value]) => (
                <div key={key} className="grid grid-cols-[180px_1fr] text-xs">
                  <dt className="px-3 py-2 bg-[var(--surface-muted)] text-[var(--text-muted)] font-medium">{key}</dt>
                  <dd className="px-3 py-2 text-[var(--text-default)]">
                    {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-xs text-[var(--text-muted)]">No frontmatter fields</p>
          )}
        </div>
      )}
    </div>
  );
};

export default WikiPage;
