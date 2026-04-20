"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiSynthesis — knowledge synthesis and gap discovery.
 */

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { WikiTabNav } from './WikiTabNav';
import { severityBg } from '@/utils/wikiColors';

interface SynthesisCluster {
  cluster_size: number;
  page_ids: string[];
  sample_titles: string[];
  key_concepts: string[];
  score: number;
}

interface Contradiction {
  type: string;
  severity: 'high' | 'medium' | 'low';
  page1_id: string;
  page1_title: string;
  page2_id: string;
  page2_title: string;
  recommendation: string;
}

interface Principle {
  principle: string;
  pattern: string;
  evidence_count: number;
  confidence: number;
  recommendation: string;
}

interface SynthesisInsights {
  synthesis_clusters: SynthesisCluster[];
  contradictions: Contradiction[];
  principles: Principle[];
  opportunities: number;
  analysis_date: string;
}

interface WikiSynthesisProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

const TABS = [
  { key: 'clusters',       label: 'Clusters' },
  { key: 'contradictions', label: 'Contradictions' },
  { key: 'principles',     label: 'Principles' },
] as const;

export const WikiSynthesis: React.FC<WikiSynthesisProps> = ({ wikiType, projectId }) => {
  const { api } = useAuth();
  const [insights, setInsights] = useState<SynthesisInsights | null>(null);
  const [loading, setLoading]   = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [notice, setNotice]     = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'clusters' | 'contradictions' | 'principles'>('clusters');

  const fetchInsights = async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/synthesis/insights?${params}`);
      if (!res.ok) throw new Error('Failed to fetch synthesis insights');
      setInsights(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    try {
      setCreating(true);
      setError(null);
      const params = new URLSearchParams();
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/synthesis/create?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error('Failed to create synthesis pages');
      const data = await res.json();
      setNotice(`Created ${data.created} synthesis pages (${data.skipped} skipped)`);
      fetchInsights();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => { fetchInsights(); }, [wikiType, projectId]);

  const tabsWithCounts = insights ? [
    { key: 'clusters',       label: `Clusters (${insights.synthesis_clusters.length})` },
    { key: 'contradictions', label: `Contradictions (${insights.contradictions.length})` },
    { key: 'principles',     label: `Principles (${insights.principles.length})` },
  ] : TABS.map((t) => ({ ...t }));

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button variant="primary" className="text-xs px-4 py-2" onClick={fetchInsights} disabled={loading}>
            {loading ? 'Analyzing…' : 'Analyze'}
          </Button>
          <Button
            variant="secondary"
            className="text-xs px-4 py-2"
            onClick={handleCreate}
            disabled={creating || !insights || insights.synthesis_clusters.length === 0}
          >
            {creating ? 'Creating…' : 'Create Synthesis Pages'}
          </Button>
        </div>
        {insights?.analysis_date && (
          <span className="text-[10px] text-[var(--text-muted)]">
            Analyzed {new Date(insights.analysis_date).toLocaleString()}
          </span>
        )}
      </div>

      {error  && <p className="text-xs text-[var(--error)]">{error}</p>}
      {notice && <p className="text-xs text-[var(--success)]">{notice}</p>}

      {insights && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-3 divide-x divide-[var(--surface-border)] border border-[var(--surface-border)]">
            {[
              { label: 'Opportunities',    value: insights.opportunities },
              { label: 'Contradictions',   value: insights.contradictions.length },
              { label: 'Principles',       value: insights.principles.length },
            ].map(({ label, value }) => (
              <div key={label} className="px-4 py-3 bg-[var(--surface-muted)]">
                <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{label}</div>
                <div className="text-lg font-semibold text-[var(--text-default)] mt-0.5">{value}</div>
              </div>
            ))}
          </div>

          <WikiTabNav tabs={tabsWithCounts} activeTab={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} />

          {/* Clusters */}
          {activeTab === 'clusters' && (
            insights.synthesis_clusters.length === 0
              ? <EmptyState title="All covered" description="All clusters already have synthesis pages." />
              : <div className="space-y-2">
                  {insights.synthesis_clusters.map((cluster, i) => (
                    <div key={i} className="border border-[var(--surface-border)] px-4 py-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-[var(--text-default)]">Cluster {i + 1}</span>
                        <span className="text-[10px] text-[var(--text-muted)]">{cluster.cluster_size} pages · score {cluster.score.toFixed(2)}</span>
                      </div>
                      {cluster.key_concepts.length > 0 && (
                        <div className="flex flex-wrap gap-1 mb-1.5">
                          {cluster.key_concepts.map((c, j) => (
                            <span key={j} className="text-[10px] px-1.5 py-0.5 border border-[var(--surface-border)] bg-white text-[var(--text-muted)] capitalize">{c}</span>
                          ))}
                        </div>
                      )}
                      {cluster.sample_titles.length > 0 && (
                        <ul className="text-xs text-[var(--text-muted)] space-y-0.5">
                          {cluster.sample_titles.map((t, j) => <li key={j}>· {t}</li>)}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
          )}

          {/* Contradictions */}
          {activeTab === 'contradictions' && (
            insights.contradictions.length === 0
              ? <EmptyState title="No contradictions" description="No conflicting information detected." />
              : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
                  {insights.contradictions.map((c, i) => (
                    <div key={i} className="px-4 py-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] border capitalize ${severityBg[c.severity]}`}>
                          {c.severity}
                        </span>
                        <span className="text-xs font-medium text-[var(--text-default)]">{c.type}</span>
                      </div>
                      <div className="text-xs text-[var(--text-muted)] space-y-0.5 mb-1.5">
                        <div>· {c.page1_title}</div>
                        <div>· {c.page2_title}</div>
                      </div>
                      <p className="text-xs text-[var(--text-default)]">→ {c.recommendation}</p>
                    </div>
                  ))}
                </div>
          )}

          {/* Principles */}
          {activeTab === 'principles' && (
            insights.principles.length === 0
              ? <EmptyState title="No principles yet" description="Principles emerge as more pages are added." />
              : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
                  {insights.principles.map((p, i) => (
                    <div key={i} className="px-4 py-3">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-xs font-medium text-[var(--text-default)]">{p.principle}</span>
                        <span className="text-[10px] text-[var(--text-muted)]">{(p.confidence * 100).toFixed(0)}% · {p.evidence_count} relationships</span>
                      </div>
                      <div className="text-[10px] text-[var(--text-muted)] font-mono mb-1">{p.pattern}</div>
                      <p className="text-xs text-[var(--text-muted)]">→ {p.recommendation}</p>
                    </div>
                  ))}
                </div>
          )}
        </>
      )}
    </div>
  );
};

export default WikiSynthesis;
