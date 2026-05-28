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
  const webEditEnabled = process.env.NEXT_PUBLIC_WIKI_WEB_EDIT_ENABLED === 'true';
  const storylineEnabled = process.env.NEXT_PUBLIC_WIKI_STORYLINE_CANVAS_ENABLED === 'true';
  const [page, setPage]       = useState<PageMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'content' | 'links' | 'relationships' | 'related' | 'metadata'>('content');
  const [relatedPages, setRelatedPages] = useState<Array<{page_id: string; relation_type: string; confidence: number; source: string}> | null>(null);
  const [relatedLoading, setRelatedLoading] = useState(false);

  useEffect(() => {
    const ac = new AbortController();
    const fetchPage = async () => {
      try {
        setLoading(true);
        setError(null);
        const params = new URLSearchParams();
        if (projectId) params.append('project_id', projectId);
        const res = await api(`/api/wiki/${wikiType}/pages/${pageId}?${params}`, { signal: ac.signal });
        if (!res.ok) throw new Error(res.status === 404 ? 'Page not found' : `Failed to load page (${res.status})`);
        const data = await res.json();
        setPage(data.page);
      } catch (e) {
        if (e instanceof Error && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    };
    fetchPage();
    return () => { ac.abort(); };
  }, [wikiType, pageId, projectId, api]);

  // Fetch related pages when the "related" tab is opened
  useEffect(() => {
    if (activeTab !== 'related' || !pageId || relatedPages !== null) return;

    const ac = new AbortController();
    const fetchRelated = async () => {
      try {
        setRelatedLoading(true);
        const params = new URLSearchParams();
        if (projectId) params.append('project_id', projectId);
        const res = await api(`/api/wiki/${wikiType}/pages/${pageId}/related?${params}`, { signal: ac.signal });
        if (!res.ok) throw new Error(`Failed to load related pages (${res.status})`);
        const data = await res.json();
        setRelatedPages(data.related_pages || []);
      } catch (e) {
        if (e instanceof Error && e.name === 'AbortError') return;
        console.warn('Failed to load related pages:', e);
      } finally {
        if (!ac.signal.aborted) setRelatedLoading(false);
      }
    };
    fetchRelated();
    return () => { ac.abort(); };
  }, [activeTab, pageId, projectId, api, relatedPages]);

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

  const renderWikiLinkedContent = (content: string) => {
    const parts = content.split(/(\[\[[^\]]+\]\])/g);
    return (
      <div className="text-sm text-[var(--text-default)] leading-relaxed whitespace-pre-wrap border-t border-[var(--surface-border)] pt-4">
        {parts.map((part, idx) => {
          const m = part.match(/^\[\[([^|\]]+)(?:\|([^\]]+))?\]\]$/);
          if (!m) return <React.Fragment key={`${idx}-${part.slice(0, 16)}`}>{part}</React.Fragment>;
          const targetId = m[1];
          const label = m[2] ?? m[1];
          return (
            <button
              key={`${idx}-${targetId}`}
              type="button"
              className="text-[var(--accent-blue)] hover:underline"
              onClick={() => onSelectPage?.(targetId)}
              disabled={!onSelectPage}
            >
              {label}
            </button>
          );
        })}
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
          {webEditEnabled && (
            <Button variant="primary" className="text-xs px-3 py-1.5">Edit</Button>
          )}
          {wikiType === 'project' && (
            <Button variant="secondary" className="text-xs px-3 py-1.5">Promote to LP</Button>
          )}
          {storylineEnabled && (
            <Button variant="ghost" className="text-xs px-3 py-1.5">Edit Storyline</Button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <WikiTabNav
        tabs={[
          { key: 'content',       label: 'Content' },
          { key: 'links',         label: `Links (${page.inbound_links.length + page.outbound_links.length})` },
          { key: 'relationships', label: 'Relationships' },
          { key: 'related',       label: 'Related Pages' },
          { key: 'metadata',      label: 'Metadata' },
        ]}
        activeTab={activeTab}
        onChange={(k) => setActiveTab(k as typeof activeTab)}
      />

      {/* Content */}
      {activeTab === 'content' && (
        renderWikiLinkedContent(page.content)
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

      {/* Related Pages (graph-discovered connections: neighbors + community + synthesis) */}
      {activeTab === 'related' && (
        <div className="pt-2 space-y-4">
          {relatedLoading ? (
            <p className="text-xs text-[var(--text-muted)]">Loading connected pages…</p>
          ) : relatedPages && relatedPages.length > 0 ? (
            <>
              {/* Group by source */}
              {['relationship', 'community', 'synthesis'].map((source) => {
                const items = relatedPages.filter(p => p.source === source);
                if (items.length === 0) return null;

                const sourceEmoji = { relationship: '🔗', community: '🏘️', synthesis: '✨' }[source as 'relationship' | 'community' | 'synthesis'] ?? '';
                const sourceText = { relationship: 'Typed Relationships', community: 'Community Peers', synthesis: 'Synthesis Pages' }[source as 'relationship' | 'community' | 'synthesis'] ?? source;
                const sourceLabel = sourceText;

                return (
                  <div key={source}>
                    <p className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide mb-2">
                      <span aria-hidden="true">{sourceEmoji} </span>{sourceLabel}
                    </p>
                    <div className="space-y-1">
                      {items.map((rel) => (
                        <button
                          key={`${rel.page_id}-${source}`}
                          type="button"
                          onClick={() => onSelectPage?.(rel.page_id)}
                          disabled={!onSelectPage}
                          className="w-full text-left text-xs text-[var(--accent-blue)] py-1 px-2 border-b border-[var(--surface-border)] hover:underline disabled:text-[var(--text-muted)] disabled:no-underline bg-[var(--surface-muted)] rounded"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span>{rel.page_id}</span>
                            <span className="text-[10px] text-[var(--text-muted)] capitalize">{rel.relation_type}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </>
          ) : (
            <p className="text-xs text-[var(--text-muted)]">No related pages discovered</p>
          )}
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
