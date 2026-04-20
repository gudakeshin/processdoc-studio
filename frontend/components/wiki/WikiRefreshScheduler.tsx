"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiRefreshScheduler — source freshness and refresh priority.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { WikiTabNav } from './WikiTabNav';

interface RefreshScheduleItem {
  page_id: string;
  priority: number;
  sources_count: number;
  last_synced: string | null;
}

interface FreshnessResult {
  page_id: string;
  has_changes: boolean;
  sources_checked: number;
  sources_changed: number;
}

interface FreshnessData {
  pages_checked: number;
  pages_with_changes: number;
  total_sources_changed: number;
  details?: FreshnessResult[];
}

interface WikiRefreshSchedulerProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  batchSize?: number;
}

const priorityLabel = (p: number) =>
  p > 50 ? 'Critical' : p > 25 ? 'High' : p > 10 ? 'Medium' : 'Low';

const priorityClass = (p: number) =>
  p > 50
    ? 'text-[var(--error)] border-[var(--error)]'
    : p > 25
    ? 'text-[var(--warning)] border-[var(--warning)]'
    : p > 10
    ? 'text-[var(--warning)] border-[var(--warning)] opacity-70'
    : 'text-[var(--success)] border-[var(--success)]';

export const WikiRefreshScheduler: React.FC<WikiRefreshSchedulerProps> = ({
  wikiType, projectId, batchSize = 10,
}) => {
  const { api } = useAuth();
  const [schedule, setSchedule]   = useState<RefreshScheduleItem[]>([]);
  const [freshness, setFreshness] = useState<FreshnessData | null>(null);
  const [loading, setLoading]     = useState(false);
  const [checking, setChecking]   = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'schedule' | 'freshness'>('schedule');

  const fetchSchedule = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ batch_size: batchSize.toString() });
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/refresh/schedule?${params}`);
      if (!res.ok) throw new Error('Failed to fetch refresh schedule');
      const data = await res.json();
      setSchedule(
        data.priority_scores
          ? Object.entries(data.priority_scores).map(([page_id, priority]) => ({
              page_id, priority: priority as number, sources_count: 0, last_synced: null,
            }))
          : []
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [batchSize, projectId, wikiType, api]);

  const checkFreshness = useCallback(async () => {
    try {
      setChecking(true);
      const params = new URLSearchParams();
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/sources/check-freshness`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error('Failed to check freshness');
      setFreshness(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setChecking(false);
    }
  }, [projectId, wikiType, api]);

  useEffect(() => {
    fetchSchedule();
    checkFreshness();
  }, [fetchSchedule, checkFreshness]);

  const tabs = [
    { key: 'schedule',  label: `Schedule (${schedule.length})` },
    { key: 'freshness', label: 'Freshness' },
  ];

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <Button variant="primary"   className="text-xs px-4 py-2" onClick={checkFreshness}  disabled={checking}>
          {checking ? 'Checking…' : 'Check Freshness'}
        </Button>
        <Button variant="secondary" className="text-xs px-4 py-2" onClick={fetchSchedule}  disabled={loading}>
          {loading ? 'Loading…' : 'Get Schedule'}
        </Button>
      </div>

      {error && <p className="text-xs text-[var(--error)]">{error}</p>}

      {/* Freshness summary strip */}
      {freshness && (
        <div className="grid grid-cols-3 divide-x divide-[var(--surface-border)] border border-[var(--surface-border)]">
          {[
            { label: 'Pages checked',    value: freshness.pages_checked        ?? 0 },
            { label: 'With changes',     value: freshness.pages_with_changes   ?? 0 },
            { label: 'Sources changed',  value: freshness.total_sources_changed ?? 0 },
          ].map(({ label, value }) => (
            <div key={label} className="px-4 py-3 bg-[var(--surface-muted)]">
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{label}</div>
              <div className="text-lg font-semibold text-[var(--text-default)] mt-0.5">{value}</div>
            </div>
          ))}
        </div>
      )}

      <WikiTabNav tabs={tabs} activeTab={activeTab} onChange={(k) => setActiveTab(k as typeof activeTab)} />

      {/* Schedule */}
      {activeTab === 'schedule' && (
        schedule.length === 0
          ? <EmptyState title="No schedule" description='Run "Check Freshness" to generate a refresh schedule.' />
          : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
              <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 px-3 py-1.5 bg-[var(--surface-muted)]">
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Page</span>
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Priority</span>
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Sources</span>
                <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">Last synced</span>
              </div>
              {schedule.slice(0, 20).map((item) => (
                <div key={item.page_id} className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 px-3 py-2 items-center">
                  <span className="text-xs font-mono text-[var(--text-default)] truncate">{item.page_id}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 border ${priorityClass(item.priority)}`}>
                    {priorityLabel(item.priority)} {item.priority.toFixed(1)}
                  </span>
                  <span className="text-xs text-[var(--text-muted)]">{item.sources_count || '—'}</span>
                  <span className="text-xs text-[var(--text-muted)] whitespace-nowrap">
                    {item.last_synced ? new Date(item.last_synced).toLocaleDateString() : 'Never'}
                  </span>
                </div>
              ))}
              {schedule.length > 20 && (
                <div className="px-3 py-2 text-xs text-[var(--text-muted)]">
                  … and {schedule.length - 20} more
                </div>
              )}
            </div>
      )}

      {/* Freshness details */}
      {activeTab === 'freshness' && (
        !freshness
          ? <p className="text-xs text-[var(--text-muted)]">Click &quot;Check Freshness&quot; to scan sources.</p>
          : freshness.pages_with_changes === 0
            ? <EmptyState
                title="All sources current"
                description={freshness.pages_checked > 0 ? `Checked ${freshness.pages_checked} pages, no changes detected.` : 'No sources checked yet.'}
              />
            : <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
                {(freshness.details ?? []).map((item, i) => (
                  <div key={i} className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-xs text-[var(--text-default)] font-mono">{item.page_id}</span>
                    <div className="text-xs text-[var(--warning)]">
                      {item.sources_changed} change{item.sources_changed !== 1 ? 's' : ''} / {item.sources_checked} checked
                    </div>
                  </div>
                ))}
              </div>
      )}
    </div>
  );
};

export default WikiRefreshScheduler;
