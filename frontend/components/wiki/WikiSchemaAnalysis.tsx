"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiSchemaAnalysis — schema evolution and pattern discovery.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { WikiTabNav } from './WikiTabNav';

interface EmergingCategory {
  category: string;
  frequency: number;
  recommendation: string;
}

interface EmergingRelationship {
  pattern: string;
  frequency: number;
  recommendation: string;
}

interface SynthesisOpportunity {
  cluster_size: number;
  page_ids: string[];
  sample_titles: string[];
  recommendation: string;
}

interface SchemaAnalysis {
  emerging_categories: EmergingCategory[];
  emerging_relationships: EmergingRelationship[];
  synthesis_opportunities: SynthesisOpportunity[];
  analysis_date: string;
}

interface WikiSchemaAnalysisProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

export const WikiSchemaAnalysis: React.FC<WikiSchemaAnalysisProps> = ({ wikiType, projectId }) => {
  const { api } = useAuth();
  const [analysis, setAnalysis] = useState<SchemaAnalysis | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'categories' | 'relationships' | 'synthesis'>('categories');

  const fetchAnalysis = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/schema/analyze?${params}`);
      if (!res.ok) throw new Error('Failed to analyze schema');
      const data = await res.json();
      setAnalysis({
        emerging_categories:    data.emerging_categories    ?? [],
        emerging_relationships: data.emerging_relationships ?? [],
        synthesis_opportunities: data.synthesis_opportunities ?? [],
        analysis_date: data.analysis_date,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [projectId, wikiType, api]);

  useEffect(() => { fetchAnalysis(); }, [fetchAnalysis]);

  if (error && !analysis) return <p className="text-xs text-[var(--error)]">{error}</p>;

  const tabs = analysis ? [
    { key: 'categories',    label: `Categories (${analysis.emerging_categories.length})` },
    { key: 'relationships', label: `Relationships (${analysis.emerging_relationships.length})` },
    { key: 'synthesis',     label: `Synthesis (${analysis.synthesis_opportunities.length})` },
  ] : [
    { key: 'categories',    label: 'Categories' },
    { key: 'relationships', label: 'Relationships' },
    { key: 'synthesis',     label: 'Synthesis' },
  ];

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3">
        <Button variant="primary" className="text-xs px-4 py-2" onClick={fetchAnalysis} disabled={loading}>
          {loading ? 'Analyzing…' : 'Re-analyze'}
        </Button>
        {analysis?.analysis_date && (
          <span className="text-[10px] text-[var(--text-muted)]">
            Analyzed {new Date(analysis.analysis_date).toLocaleString()}
          </span>
        )}
      </div>

      {error && <p className="text-xs text-[var(--error)]">{error}</p>}

      {!analysis && loading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <div key={i} className="h-8 bg-[var(--surface-muted)] animate-pulse" />)}
        </div>
      )}

      {analysis && (
        <>
          <WikiTabNav tabs={tabs} activeTab={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} />

          {/* Categories */}
          {activeTab === 'categories' && (
            analysis.emerging_categories.length === 0
              ? <EmptyState title="Schema matches" description="All used categories are already documented." />
              : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
                  {analysis.emerging_categories.map((cat, i) => (
                    <div key={i} className="flex items-start justify-between px-4 py-3 gap-3">
                      <div>
                        <div className="text-xs font-medium text-[var(--text-default)] capitalize">{cat.category}</div>
                        <p className="text-xs text-[var(--text-muted)] mt-0.5">{cat.recommendation}</p>
                      </div>
                      <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">{cat.frequency} pages</span>
                    </div>
                  ))}
                </div>
          )}

          {/* Relationships */}
          {activeTab === 'relationships' && (
            analysis.emerging_relationships.length === 0
              ? <EmptyState title="All types documented" description="No new relationship patterns detected." />
              : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
                  {analysis.emerging_relationships.map((rel, i) => (
                    <div key={i} className="flex items-start justify-between px-4 py-3 gap-3">
                      <div>
                        <div className="text-xs font-medium text-[var(--text-default)] font-mono">{rel.pattern}</div>
                        <p className="text-xs text-[var(--text-muted)] mt-0.5">{rel.recommendation}</p>
                      </div>
                      <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">{rel.frequency}×</span>
                    </div>
                  ))}
                </div>
          )}

          {/* Synthesis */}
          {activeTab === 'synthesis' && (
            analysis.synthesis_opportunities.length === 0
              ? <EmptyState title="All clusters covered" description="No synthesis opportunities detected." />
              : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
                  {analysis.synthesis_opportunities.map((opp, i) => (
                    <div key={i} className="px-4 py-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-[var(--text-default)]">{opp.recommendation}</span>
                        <span className="text-[10px] text-[var(--text-muted)]">{opp.cluster_size} pages</span>
                      </div>
                      {opp.sample_titles.length > 0 && (
                        <ul className="text-xs text-[var(--text-muted)] space-y-0.5 mt-1">
                          {opp.sample_titles.map((t, j) => <li key={j}>· {t}</li>)}
                          {opp.page_ids.length > opp.sample_titles.length && (
                            <li>· … and {opp.page_ids.length - opp.sample_titles.length} more</li>
                          )}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
          )}
        </>
      )}
    </div>
  );
};

export default WikiSchemaAnalysis;
