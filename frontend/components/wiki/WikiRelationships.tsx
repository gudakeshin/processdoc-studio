"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiRelationships — typed relationships and transitive inference.
 */

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { WikiTabNav } from './WikiTabNav';
import { severityBg } from '@/utils/wikiColors';

interface RelationshipStats {
  total_relationships: number;
  by_type: Record<string, number>;
  pages_with_relationships: number;
  average_relationships_per_page: number;
}

interface RelatedPage {
  page_id: string;
  relation_type: string;
  confidence: number;
}

interface ValidationIssue {
  type: string;
  severity: 'high' | 'medium' | 'low';
  message: string;
  cycle?: string;
}

interface WikiRelationshipsProps {
  wikiType: 'leading_practice' | 'project';
  pageId?: string;
  projectId?: string;
}

export const WikiRelationships: React.FC<WikiRelationshipsProps> = ({ wikiType, pageId, projectId }) => {
  const { api } = useAuth();
  const [stats, setStats]               = useState<RelationshipStats | null>(null);
  const [relatedPages, setRelatedPages] = useState<RelatedPage[]>([]);
  const [issues, setIssues]             = useState<ValidationIssue[]>([]);
  const [classifying, setClassifying]   = useState(false);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const [classifyNotice, setClassifyNotice] = useState<string | null>(null);
  const [activeTab, setActiveTab]       = useState<'stats' | 'related' | 'validation'>('stats');

  useEffect(() => {
    const fetchStats = async () => {
      try {
        setLoading(true);
        const params = new URLSearchParams();
        if (projectId) params.append('project_id', projectId);
        const res = await api(`/api/wiki/${wikiType}/relationships/validate?${params}`);
        if (!res.ok) throw new Error('Failed to fetch relationship stats');
        const data = await res.json();
        setStats({
          total_relationships: data.total_relationships,
          by_type: data.by_type ?? {},
          pages_with_relationships: data.pages_with_relationships ?? 0,
          average_relationships_per_page: data.average_relationships_per_page ?? 0,
        });
        setIssues(data.issues ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, [wikiType, projectId, api]);

  useEffect(() => {
    if (!pageId) return;
    const fetch_ = async () => {
      try {
        const params = new URLSearchParams();
        if (projectId) params.append('project_id', projectId);
        const res = await api(`/api/wiki/${wikiType}/pages/${pageId}/related?${params}`);
        if (!res.ok) return;
        const data = await res.json();
        setRelatedPages(data.related_pages ?? []);
      } catch {}
    };
    fetch_();
  }, [wikiType, pageId, projectId, api]);

  const handleClassify = async () => {
    try {
      setClassifying(true);
      setError(null);
      const params = new URLSearchParams();
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/relationships/classify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error('Failed to classify relationships');
      const data = await res.json();
      setStats({
        total_relationships: data.total_relationships,
        by_type: data.by_type ?? {},
        pages_with_relationships: data.pages_with_relationships ?? 0,
        average_relationships_per_page: data.average_relationships_per_page ?? 0,
      });
      setClassifyNotice(`Classified ${data.classified} relationships`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setClassifying(false);
    }
  };

  const tabs = [
    { key: 'stats',      label: 'Statistics' },
    { key: 'related',    label: pageId ? 'Related Pages' : 'Related' },
    { key: 'validation', label: `Validation${issues.length > 0 ? ` (${issues.length})` : ''}` },
  ];

  if (error && !stats) return <p className="text-xs text-[var(--error)]">{error}</p>;

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <Button variant="primary" className="text-xs px-4 py-2" onClick={handleClassify} disabled={classifying}>
          {classifying ? 'Classifying…' : 'Auto-Classify'}
        </Button>
      </div>

      {error        && <p className="text-xs text-[var(--error)]">{error}</p>}
      {classifyNotice && <p className="text-xs text-[var(--success)]">{classifyNotice}</p>}

      <WikiTabNav tabs={tabs} activeTab={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} />

      {/* Statistics */}
      {activeTab === 'stats' && stats && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-[var(--surface-border)] border border-[var(--surface-border)]">
            {[
              { label: 'Relationships', value: stats.total_relationships },
              { label: 'Pages linked',  value: stats.pages_with_relationships },
              { label: 'Avg per page',  value: stats.average_relationships_per_page.toFixed(1) },
              { label: 'Types',         value: Object.keys(stats.by_type).length },
            ].map(({ label, value }) => (
              <div key={label} className="px-4 py-3 bg-[var(--surface-muted)]">
                <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{label}</div>
                <div className="text-lg font-semibold text-[var(--text-default)] mt-0.5">{value}</div>
              </div>
            ))}
          </div>

          {Object.keys(stats.by_type).length > 0 && (
            <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
              {Object.entries(stats.by_type)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between px-4 py-2">
                    <span className="text-xs text-[var(--text-default)] capitalize">{type.replace(/_/g, ' ')}</span>
                    <span className="text-xs text-[var(--text-muted)]">{count}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}

      {/* Related Pages */}
      {activeTab === 'related' && (
        !pageId
          ? <p className="text-xs text-[var(--text-muted)]">Select a page to view related pages.</p>
          : relatedPages.length === 0
            ? <EmptyState title="No related pages" description="No relationships found for this page." />
            : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
                {relatedPages.map((p) => (
                  <div key={p.page_id} className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-xs text-[var(--text-default)] font-mono">{p.page_id}</span>
                    <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                      <span className="capitalize">{p.relation_type.replace(/_/g, ' ')}</span>
                      <span>{(p.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                ))}
              </div>
      )}

      {/* Validation */}
      {activeTab === 'validation' && (
        issues.length === 0
          ? <EmptyState title="No issues" description="All relationships are valid." />
          : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
              {issues.map((issue, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] border capitalize ${severityBg[issue.severity]}`}>
                      {issue.severity}
                    </span>
                    <span className="text-xs font-medium text-[var(--text-default)]">{issue.type}</span>
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">{issue.message}</p>
                  {issue.cycle && (
                    <code className="mt-1 block text-[10px] text-[var(--text-muted)] font-mono">{issue.cycle}</code>
                  )}
                </div>
              ))}
            </div>
      )}
    </div>
  );
};

export default WikiRelationships;
