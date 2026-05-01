"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiDashboard — compact overview with live stats.
 * Auto-syncs uningested project documents on mount.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';

interface WikiStats {
  total_pages: number;
  by_category: Record<string, number>;
  by_confidence: Record<string, number>;
  last_ingest?: string;
  pages_this_week: number;
  health: {
    severity: 'low' | 'medium' | 'high';
    issues_count: number;
    stale_pages: number;
  };
}

interface WikiScorecard {
  lint?: { severity?: string; summary?: Record<string, number> };
  relationship_validation?: { issues_count?: number; total_relationships?: number };
  freshness?: { maintenance_updated_at?: string | null };
}

interface SyncResult {
  synced: number;
  already_synced: number;
  errors: number;
  total_files: number;
}

interface WikiDashboardProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

export const WikiDashboard: React.FC<WikiDashboardProps> = ({ wikiType, projectId }) => {
  const { api } = useAuth();
  const [stats, setStats]       = useState<WikiStats | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [syncing, setSyncing]   = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const [vaultPath, setVaultPath] = useState<string | null>(null);
  const [scorecard, setScorecard] = useState<WikiScorecard | null>(null);
  const [cleaning, setCleaning] = useState(false);
  const [cleanupMessage, setCleanupMessage] = useState<string | null>(null);
  const storylineEnabled = process.env.NEXT_PUBLIC_WIKI_STORYLINE_CANVAS_ENABLED === 'true';

  const fetchStats = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/stats?${params}`);
      if (!res.ok) throw new Error('Failed to fetch stats');
      const data = await res.json();
      setStats(data.stats);
      const scoreRes = await api(`/api/wiki/${wikiType}/health/scorecard?${params}`);
      if (scoreRes.ok) {
        const scoreData = await scoreRes.json();
        setScorecard(scoreData.scorecard ?? null);
      } else {
        setScorecard(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [wikiType, projectId, api]);

  const initAndOpenVault = useCallback(async () => {
    if (wikiType !== 'project' || !projectId) return;
    try {
      await api(`/api/wiki/project/${projectId}/vault/init`, { method: 'POST' });
      const pathRes = await api(`/api/wiki/project/${projectId}/vault/path`);
      if (pathRes.ok) {
        const pathData = await pathRes.json();
        setVaultPath(pathData.vault_path ?? null);
      }
      window.location.href = `obsidian://open?vault=${encodeURIComponent(projectId)}`;
    } catch {
      // Keep dashboard functional even if Obsidian isn't installed.
    }
  }, [wikiType, projectId, api]);

  const cleanupOrphans = useCallback(async () => {
    if (wikiType !== 'project' || !projectId) return;
    setCleaning(true);
    setCleanupMessage(null);
    try {
      const params = new URLSearchParams({ project_id: projectId });
      const res = await api(`/api/wiki/project/cleanup-orphans?${params}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setCleanupMessage(`Removed ${data.deleted} orphaned page${data.deleted === 1 ? '' : 's'}.`);
        await fetchStats();
      } else {
        setCleanupMessage('Cleanup failed.');
      }
    } catch {
      setCleanupMessage('Cleanup failed.');
    } finally {
      setCleaning(false);
    }
  }, [wikiType, projectId, api, fetchStats]);

  // Auto-sync project documents on mount
  useEffect(() => {
    const syncAndFetch = async () => {
      if (wikiType === 'project' && projectId) {
        setSyncing(true);
        try {
          const params = new URLSearchParams({ project_id: projectId });
          const res = await api(`/api/wiki/project/sync-documents?${params}`, { method: 'POST' });
          if (res.ok) {
            const result: SyncResult = await res.json();
            if (result.synced > 0) setSyncResult(result);
          }
        } catch {
          // non-blocking — sync failure shouldn't break the page
        } finally {
          setSyncing(false);
        }
      }
      await fetchStats();
    };
    void syncAndFetch();
  }, [wikiType, projectId, fetchStats, api]);

  if (loading || syncing) {
    return (
      <div className="space-y-3">
        {syncing && (
          <p className="text-xs text-[var(--text-muted)]">Syncing project documents into wiki…</p>
        )}
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-8 bg-[var(--surface-muted)] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return <p className="text-xs text-[var(--error)]">{error}</p>;
  }

  if (!stats || stats.total_pages === 0) {
    return (
      <EmptyState
        title="No pages yet"
        description="Upload documents in Run Studio — they'll appear here automatically. You can also ingest URLs or other sources from the Ingest tab."
      />
    );
  }

  const healthColor =
    stats.health.severity === 'high'   ? 'text-[var(--error)]' :
    stats.health.severity === 'medium' ? 'text-[var(--warning)]' :
                                          'text-[var(--success)]';

  const lastIngest = stats.last_ingest
    ? new Date(stats.last_ingest).toLocaleDateString()
    : '—';
  const lintSeverity = scorecard?.lint?.severity ?? stats.health.severity;
  const relationshipsTotal = scorecard?.relationship_validation?.total_relationships ?? 0;
  const relationshipIssues = scorecard?.relationship_validation?.issues_count ?? 0;

  return (
    <div className="space-y-5">
      {/* Sync banner — shown only when new docs were just synced */}
      {syncResult && syncResult.synced > 0 && (
        <div className="border border-[var(--surface-border)] px-4 py-2 bg-[var(--surface-muted)] text-xs text-[var(--success)]">
          {syncResult.synced} project document{syncResult.synced !== 1 ? 's' : ''} added to wiki.
          {syncResult.errors > 0 && (
            <span className="text-[var(--warning)] ml-2">{syncResult.errors} failed.</span>
          )}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-[var(--surface-border)] border border-[var(--surface-border)]">
        {[
          { label: 'Pages',            value: stats.total_pages },
          { label: 'Categories',       value: Object.keys(stats.by_category).length },
          { label: 'Added this week',  value: stats.pages_this_week },
          { label: 'Last ingest',      value: lastIngest },
        ].map(({ label, value }) => (
          <div key={label} className="px-4 py-3 bg-[var(--surface-muted)]">
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{label}</div>
            <div className="text-lg font-semibold text-[var(--text-default)] mt-0.5">{value}</div>
          </div>
        ))}
      </div>

      {/* Health row */}
      <div className="flex items-center gap-2 text-xs border border-[var(--surface-border)] px-4 py-2 bg-[var(--surface-muted)]">
        <span className="text-[var(--text-muted)]">Health:</span>
        <span className={`font-medium capitalize ${healthColor}`}>{stats.health.severity}</span>
        {stats.health.issues_count > 0 && (
          <span className="text-[var(--text-muted)]">· {stats.health.issues_count} issue{stats.health.issues_count !== 1 ? 's' : ''}</span>
        )}
        {stats.health.stale_pages > 0 && (
          <span className="text-[var(--text-muted)]">· {stats.health.stale_pages} stale</span>
        )}
      </div>

      {scorecard && (
        <div className="border border-[var(--surface-border)] px-4 py-3 bg-[var(--surface-muted)] text-xs">
          <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] mb-1">Health scorecard</div>
          <div className="flex flex-wrap gap-3 text-[var(--text-muted)]">
            <span>Lint: <span className="capitalize text-[var(--text-default)]">{lintSeverity}</span></span>
            <span>Relationships: <span className="text-[var(--text-default)]">{relationshipsTotal}</span></span>
            <span>Relationship issues: <span className="text-[var(--text-default)]">{relationshipIssues}</span></span>
            {scorecard.freshness?.maintenance_updated_at && (
              <span>
                Maintained: <span className="text-[var(--text-default)]">
                  {new Date(scorecard.freshness.maintenance_updated_at).toLocaleDateString()}
                </span>
              </span>
            )}
          </div>
        </div>
      )}

      {wikiType === 'project' && projectId && (
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="secondary" className="text-xs px-3 py-1.5" onClick={initAndOpenVault}>
            Open in Obsidian
          </Button>
          <Button
            variant="ghost"
            className="text-xs px-3 py-1.5"
            onClick={cleanupOrphans}
            disabled={cleaning}
          >
            {cleaning ? 'Cleaning…' : 'Clean up orphaned pages'}
          </Button>
          {cleanupMessage && (
            <span className="text-[10px] text-[var(--text-muted)]">{cleanupMessage}</span>
          )}
          {vaultPath && (
            <span className="text-[10px] text-[var(--text-muted)] font-mono">{vaultPath}</span>
          )}
          {storylineEnabled && (
            <Button variant="ghost" className="text-xs px-3 py-1.5">
              Open Storyline Canvas
            </Button>
          )}
        </div>
      )}

      {/* Category breakdown */}
      {Object.keys(stats.by_category).length > 0 && (
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-2">By category</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.by_category)
              .sort((a, b) => b[1] - a[1])
              .map(([cat, count]) => (
                <span
                  key={cat}
                  className="px-2 py-1 text-xs border border-[var(--surface-border)] bg-white text-[var(--text-default)] capitalize"
                >
                  {cat} <span className="text-[var(--text-muted)]">{count}</span>
                </span>
              ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default WikiDashboard;
