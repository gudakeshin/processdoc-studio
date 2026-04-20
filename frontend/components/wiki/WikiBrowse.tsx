"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiBrowse — compact table-style page list with inline filters.
 */

import React, { useState, useEffect } from 'react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { confidenceClass } from '@/utils/wikiColors';

interface BrowseItem {
  id: string;
  title: string;
  category: string;
  confidence: string;
  updated_at: string;
  summary?: string;
  inbound_links?: number;
}

interface WikiBrowseProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  onPageSelect?: (pageId: string) => void;
}

const CATEGORIES = ['entity', 'concept', 'decision', 'learning', 'template', 'artifact', 'document', 'note'];

export const WikiBrowse: React.FC<WikiBrowseProps> = ({ wikiType, projectId, onPageSelect }) => {
  const { api } = useAuth();
  const [pages, setPages]         = useState<BrowseItem[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [sortBy, setSortBy]       = useState<'updated_at' | 'title'>('updated_at');
  const [currentPage, setCurrentPage] = useState(1);
  const [total, setTotal]         = useState(0);
  const perPage = 25;

  useEffect(() => {
    let cancelled = false;
    const fetchPages = async () => {
      try {
        setLoading(true);
        setError(null);
        const params = new URLSearchParams({
          limit: perPage.toString(),
          offset: ((currentPage - 1) * perPage).toString(),
          sort_by: sortBy,
        });
        if (projectId) params.append('project_id', projectId);
        if (categoryFilter) params.append('category', categoryFilter);

        const res = await api(`/api/wiki/${wikiType}/pages?${params}`);
        if (!res.ok) throw new Error(`Failed to fetch pages (${res.status})`);
        const data = await res.json();
        if (cancelled) return;
        setPages(data.pages ?? []);
        setTotal(data.pagination?.total ?? 0);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchPages();
    return () => { cancelled = true; };
  }, [wikiType, projectId, currentPage, sortBy, categoryFilter, api]);

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {/* Category chips */}
        <div className="flex flex-wrap gap-1.5 items-center">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mr-1">Filter:</span>
          <button
            onClick={() => { setCategoryFilter(null); setCurrentPage(1); }}
            className={`px-2 py-0.5 text-xs border transition ${
              !categoryFilter
                ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white'
                : 'border-[var(--surface-border)] text-[var(--text-muted)] hover:border-[var(--text-default)]'
            }`}
          >
            All
          </button>
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => { setCategoryFilter(cat); setCurrentPage(1); }}
              className={`px-2 py-0.5 text-xs border capitalize transition ${
                categoryFilter === cat
                  ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white'
                  : 'border-[var(--surface-border)] text-[var(--text-muted)] hover:border-[var(--text-default)]'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Sort + count */}
        <div className="flex items-center gap-3 text-xs text-[var(--text-muted)]">
          <span>{total} page{total !== 1 ? 's' : ''}</span>
          <span>Sort:</span>
          {(['updated_at', 'title'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSortBy(s)}
              className={`${sortBy === s ? 'text-[var(--accent-blue)] font-medium' : 'hover:text-[var(--text-default)]'}`}
            >
              {s === 'updated_at' ? 'Recent' : 'A–Z'}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && <p className="text-xs text-[var(--error)]">{error}</p>}

      {/* Loading skeleton */}
      {loading && (
        <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="px-3 py-2.5 flex gap-3">
              <div className="h-3 w-48 bg-[var(--surface-muted)] animate-pulse" />
              <div className="h-3 w-16 bg-[var(--surface-muted)] animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      {!loading && pages.length === 0 && (
        <EmptyState
          title="No pages found"
          description={categoryFilter ? `No pages in category "${categoryFilter}"` : 'Ingest sources to populate the wiki.'}
        />
      )}

      {!loading && pages.length > 0 && (
        <>
          <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
            {/* Header */}
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 px-3 py-1.5 bg-[var(--surface-muted)]">
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Title</span>
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Category</span>
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Confidence</span>
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Updated</span>
            </div>

            {pages.map((page) => (
              <div
                key={page.id}
                onClick={() => onPageSelect?.(page.id)}
                className={`grid grid-cols-[1fr_auto_auto_auto] gap-x-4 px-3 py-2.5 items-center ${
                  onPageSelect ? 'cursor-pointer hover:bg-[var(--surface-muted)]' : ''
                } transition`}
              >
                <div>
                  <span className={`text-sm font-medium ${onPageSelect ? 'text-[var(--accent-blue)]' : 'text-[var(--text-default)]'}`}>
                    {page.title}
                  </span>
                  {page.summary && (
                    <p className="text-xs text-[var(--text-muted)] mt-0.5 truncate max-w-sm">{page.summary}</p>
                  )}
                </div>
                <Badge className="text-[10px] capitalize">{page.category}</Badge>
                <span className={`inline-flex items-center px-2 py-0.5 text-[10px] border capitalize ${confidenceClass[page.confidence] ?? confidenceClass.medium}`}>
                  {page.confidence}
                </span>
                <span className="text-xs text-[var(--text-muted)] whitespace-nowrap">
                  {new Date(page.updated_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
              <span>
                {(currentPage - 1) * perPage + 1}–{Math.min(currentPage * perPage, total)} of {total}
              </span>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  className="px-2 py-1 text-xs"
                  disabled={currentPage === 1}
                  onClick={() => setCurrentPage((p) => p - 1)}
                >
                  ←
                </Button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const n = Math.max(1, currentPage - 2) + i;
                  if (n > totalPages) return null;
                  return (
                    <Button
                      key={n}
                      variant={n === currentPage ? 'secondary' : 'ghost'}
                      className="px-2 py-1 text-xs min-w-[28px]"
                      onClick={() => setCurrentPage(n)}
                    >
                      {n}
                    </Button>
                  );
                })}
                <Button
                  variant="ghost"
                  className="px-2 py-1 text-xs"
                  disabled={currentPage === totalPages}
                  onClick={() => setCurrentPage((p) => p + 1)}
                >
                  →
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default WikiBrowse;
