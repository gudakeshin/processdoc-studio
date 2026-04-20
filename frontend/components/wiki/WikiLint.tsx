"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiLint — health check and issue browser.
 */

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { severityBg, severityBorder } from '@/utils/wikiColors';

interface Issue {
  id: string;
  type: 'contradiction' | 'orphan' | 'broken_link' | 'missing_reference' | 'coverage_gap' | 'divergence' | 'staleness';
  severity: 'low' | 'medium' | 'high';
  title: string;
  description: string;
  affected_pages: string[];
  suggestion?: string;
}

interface LintResult {
  status: 'success' | 'error';
  passed: boolean;
  issues_count: number;
  issues: Issue[];
  suggestions: string[];
  severity: 'low' | 'medium' | 'high';
  timestamp: string;
  auto_fixes_applied?: number;
  error?: string;
}

interface WikiLintProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  autoRun?: boolean;
}

type IssueFilter = 'all' | Issue['type'];
type SeverityFilter = 'all' | 'low' | 'medium' | 'high';

const ISSUE_LABELS: Record<string, string> = {
  contradiction:      'Contradiction',
  orphan:             'Orphan',
  broken_link:        'Broken Link',
  missing_reference:  'Missing Ref',
  coverage_gap:       'Gap',
  divergence:         'Divergence',
  staleness:          'Stale',
};

export const WikiLint: React.FC<WikiLintProps> = ({ wikiType, projectId, autoRun = false }) => {
  const { api } = useAuth();
  const [result, setResult]         = useState<LintResult | null>(null);
  const [loading, setLoading]       = useState(autoRun);
  const [error, setError]           = useState<string | null>(null);
  const [autoFix, setAutoFix]       = useState(false);
  const [issueFilter, setIssueFilter]       = useState<IssueFilter>('all');
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [expandedIssue, setExpandedIssue]   = useState<string | null>(null);

  useEffect(() => { if (autoRun) runLint(); }, []);

  const runLint = async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({ auto_fix: autoFix.toString() });
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/lint?${params}`, { method: 'POST' });
      if (!res.ok) throw new Error('Lint failed');
      setResult(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const visible = result?.issues.filter((i) =>
    (issueFilter === 'all' || i.type === issueFilter) &&
    (severityFilter === 'all' || i.severity === severityFilter)
  ) ?? [];

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center gap-4">
        <Button variant="primary" className="text-xs px-4 py-2" onClick={runLint} disabled={loading}>
          {loading ? 'Checking…' : 'Run Health Check'}
        </Button>
        <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] cursor-pointer">
          <input type="checkbox" checked={autoFix} onChange={(e) => setAutoFix(e.target.checked)} />
          Auto-fix
        </label>
      </div>

      {error && <p className="text-xs text-[var(--error)]">{error}</p>}

      {result && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-[var(--surface-border)] border border-[var(--surface-border)]">
            {[
              { label: 'Status',     value: result.passed ? 'Healthy' : 'Issues' },
              { label: 'Issues',     value: result.issues_count },
              { label: 'Severity',   value: result.severity },
              { label: 'Auto-fixed', value: result.auto_fixes_applied ?? '—' },
            ].map(({ label, value }) => (
              <div key={label} className="px-4 py-3 bg-[var(--surface-muted)]">
                <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{label}</div>
                <div className={`text-lg font-semibold mt-0.5 capitalize ${
                  label === 'Status'
                    ? result.passed ? 'text-[var(--success)]' : 'text-[var(--error)]'
                    : label === 'Severity'
                    ? result.severity === 'high' ? 'text-[var(--error)]' : result.severity === 'medium' ? 'text-[var(--warning)]' : 'text-[var(--success)]'
                    : 'text-[var(--text-default)]'
                }`}>
                  {value}
                </div>
              </div>
            ))}
          </div>

          {/* Issue type filter */}
          <div className="flex flex-wrap gap-1 items-center text-xs">
            <button
              onClick={() => setIssueFilter('all')}
              className={`px-2 py-0.5 border transition ${!issueFilter || issueFilter === 'all' ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white' : 'border-[var(--surface-border)] text-[var(--text-muted)] hover:border-[var(--text-default)]'}`}
            >
              All
            </button>
            {Object.entries(ISSUE_LABELS).map(([type, label]) => {
              const count = result.issues.filter((i) => i.type === type).length;
              if (count === 0) return null;
              return (
                <button
                  key={type}
                  onClick={() => setIssueFilter(type as IssueFilter)}
                  className={`px-2 py-0.5 border transition ${issueFilter === type ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white' : 'border-[var(--surface-border)] text-[var(--text-muted)] hover:border-[var(--text-default)]'}`}
                >
                  {label} <span className="opacity-70">{count}</span>
                </button>
              );
            })}
            <span className="mx-1 text-[var(--surface-border)]">|</span>
            {(['all', 'high', 'medium', 'low'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSeverityFilter(s)}
                className={`px-2 py-0.5 border capitalize transition ${severityFilter === s ? 'border-[var(--text-default)] bg-[var(--text-default)] text-white' : 'border-[var(--surface-border)] text-[var(--text-muted)] hover:border-[var(--text-default)]'}`}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Issues */}
          {visible.length === 0 ? (
            <EmptyState
              title={result.issues_count === 0 ? 'Wiki is healthy' : 'No matching issues'}
              description={result.issues_count === 0 ? 'No issues detected.' : 'Adjust the filters above.'}
            />
          ) : (
            <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
              {visible.map((issue) => (
                <div key={issue.id}>
                  <button
                    onClick={() => setExpandedIssue(expandedIssue === issue.id ? null : issue.id)}
                    className="w-full px-4 py-3 flex items-start justify-between text-left hover:bg-[var(--surface-muted)] transition"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] border capitalize ${severityBg[issue.severity]}`}>
                          {issue.severity}
                        </span>
                        <span className="text-xs font-medium text-[var(--text-default)]">{issue.title}</span>
                      </div>
                      <p className="text-xs text-[var(--text-muted)] truncate">{issue.description}</p>
                    </div>
                    <span className="text-[var(--text-muted)] ml-3 text-xs">{expandedIssue === issue.id ? '▼' : '▶'}</span>
                  </button>

                  {expandedIssue === issue.id && (
                    <div className="px-4 py-3 bg-[var(--surface-muted)] border-t border-[var(--surface-border)] space-y-3">
                      {issue.affected_pages.length > 0 && (
                        <div>
                          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1">Affected pages</p>
                          {issue.affected_pages.map((p, i) => (
                            <div key={i} className="text-xs text-[var(--text-default)]">· {p}</div>
                          ))}
                        </div>
                      )}
                      {issue.suggestion && (
                        <div className={`px-3 py-2 border-l-2 ${severityBorder[issue.severity]} text-xs text-[var(--text-default)]`}>
                          {issue.suggestion}
                        </div>
                      )}
                      <div className="flex gap-2">
                        <Button variant="ghost" className="text-xs px-3 py-1">Resolve</Button>
                        <Button variant="ghost" className="text-xs px-3 py-1">Ignore</Button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Suggestions */}
          {result.suggestions.length > 0 && (
            <div className="border border-[var(--surface-border)] px-4 py-3 bg-[var(--surface-muted)]">
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-2">Recommendations</p>
              <ul className="space-y-1">
                {result.suggestions.map((s, i) => (
                  <li key={i} className="text-xs text-[var(--text-default)] flex gap-2">
                    <span className="text-[var(--accent-blue)]">→</span>{s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-[10px] text-[var(--text-muted)]">
            Last checked: {new Date(result.timestamp).toLocaleString()}
          </p>
        </>
      )}

      {!result && !loading && (
        <div className="border border-[var(--surface-border)] px-4 py-3 bg-[var(--surface-muted)]">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1.5">What gets checked</p>
          <ul className="text-xs text-[var(--text-muted)] space-y-0.5 list-disc list-inside">
            <li>Contradictions — conflicting claims across pages</li>
            <li>Orphan pages — no incoming links</li>
            <li>Broken links — references to non-existent pages</li>
            <li>Coverage gaps — important topics under-documented</li>
            <li>Staleness — pages not updated despite newer sources</li>
          </ul>
        </div>
      )}
    </div>
  );
};

export default WikiLint;
