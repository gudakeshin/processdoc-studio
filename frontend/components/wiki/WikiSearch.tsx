"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiSearch — full-text search with inline filters.
 */

import React, { useState } from 'react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { confidenceClass } from '@/utils/wikiColors';

interface SearchResult {
  id: string;
  title: string;
  category: string;
  confidence: string;
  content: string;
  updated_at: string;
}

interface WikiSearchProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

export const WikiSearch: React.FC<WikiSearchProps> = ({ wikiType, projectId }) => {
  const { api } = useAuth();
  const [query, setQuery]     = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [catFilter, setCatFilter]   = useState<string | null>(null);
  const [confFilter, setConfFilter] = useState<string | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({ q: query });
      if (projectId) params.append('project_id', projectId);
      if (catFilter)  params.append('category', catFilter);
      if (confFilter) params.append('confidence', confFilter);
      const res = await api(`/api/wiki/${wikiType}/search?${params}`);
      if (!res.ok) throw new Error('Search failed');
      const data = await res.json();
      setResults(data.results ?? []);
      setSearched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const categories   = [...new Set(results.map((r) => r.category))];
  const confidences  = [...new Set(results.map((r) => r.confidence))];
  const visible = results.filter(
    (r) => (!catFilter || r.category === catFilter) && (!confFilter || r.confidence === confFilter)
  );

  return (
    <div className="space-y-4">
      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search wiki pages"
          placeholder="Search wiki pages…"
          className="flex-1 px-3 py-2 text-sm border border-[var(--surface-border)] bg-white text-[var(--text-default)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-blue)]"
        />
        <Button type="submit" variant="primary" className="text-xs px-4 py-2" disabled={loading}>
          {loading ? 'Searching…' : 'Search'}
        </Button>
      </form>

      {error && <p className="text-xs text-[var(--error)]">{error}</p>}

      {/* Filters (only shown when there are results) */}
      {searched && results.length > 0 && (
        <div className="flex flex-wrap gap-3 items-center text-xs text-[var(--text-muted)]">
          <span>{visible.length} result{visible.length !== 1 ? 's' : ''}</span>
          {categories.length > 1 && (
            <div className="flex gap-1 items-center">
              <span>Category:</span>
              <button onClick={() => setCatFilter(null)} className={`px-2 py-0.5 border transition ${!catFilter ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white' : 'border-[var(--surface-border)] hover:border-[var(--text-default)]'}`}>All</button>
              {categories.map((c) => (
                <button key={c} onClick={() => setCatFilter(c)} className={`px-2 py-0.5 border capitalize transition ${catFilter === c ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white' : 'border-[var(--surface-border)] hover:border-[var(--text-default)]'}`}>{c}</button>
              ))}
            </div>
          )}
          {confidences.length > 1 && (
            <div className="flex gap-1 items-center">
              <span>Confidence:</span>
              <button onClick={() => setConfFilter(null)} className={`px-2 py-0.5 border transition ${!confFilter ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white' : 'border-[var(--surface-border)] hover:border-[var(--text-default)]'}`}>All</button>
              {confidences.map((c) => (
                <button key={c} onClick={() => setConfFilter(c)} className={`px-2 py-0.5 border capitalize transition ${confFilter === c ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white' : 'border-[var(--surface-border)] hover:border-[var(--text-default)]'}`}>{c}</button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Results */}
      {searched && visible.length === 0 && !loading && (
        <EmptyState title="No results" description={`Nothing found for "${query}"`} />
      )}

      {visible.length > 0 && (
        <div className="divide-y divide-[var(--surface-border)] border border-[var(--surface-border)]">
          {visible.map((r) => (
            <div key={r.id} className="px-4 py-3 hover:bg-[var(--surface-muted)] transition">
              <div className="flex items-start justify-between gap-3 mb-1">
                <span className="text-sm font-medium text-[var(--accent-blue)]">{r.title}</span>
                <div className="flex gap-1.5 flex-shrink-0">
                  <Badge className="text-[10px] capitalize">{r.category}</Badge>
                  <span className={`inline-flex items-center px-2 py-0.5 text-[10px] border capitalize ${confidenceClass[r.confidence] ?? confidenceClass.medium}`}>
                    {r.confidence}
                  </span>
                </div>
              </div>
              {r.content && (
                <p className="text-xs text-[var(--text-muted)] line-clamp-2">{r.content}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default WikiSearch;
