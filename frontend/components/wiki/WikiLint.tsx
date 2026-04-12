/**
 * WikiLint - Health check and issue resolution interface
 *
 * Features:
 * - Run health check on wiki
 * - Display issues by category and severity
 * - Suggestions and recommendations
 * - Auto-fix capabilities
 * - Historical trend view
 */

import React, { useState, useEffect } from 'react';

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

type IssueFilter = 'all' | 'contradiction' | 'orphan' | 'broken_link' | 'missing_reference' | 'coverage_gap' | 'divergence' | 'staleness';
type SeverityFilter = 'all' | 'low' | 'medium' | 'high';

export const WikiLint: React.FC<WikiLintProps> = ({
  wikiType,
  projectId,
  autoRun = false,
}) => {
  const [result, setResult] = useState<LintResult | null>(null);
  const [loading, setLoading] = useState(autoRun);
  const [error, setError] = useState<string | null>(null);
  const [autoFix, setAutoFix] = useState(false);
  const [issueFilter, setIssueFilter] = useState<IssueFilter>('all');
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [expandedIssue, setExpandedIssue] = useState<string | null>(null);

  useEffect(() => {
    if (autoRun) {
      runLint();
    }
  }, []);

  const runLint = async () => {
    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams({
        auto_fix: autoFix.toString(),
      });

      if (projectId) params.append('project_id', projectId);

      const response = await fetch(
        `/api/wiki/${wikiType}/lint?${params.toString()}`,
        { method: 'POST' }
      );

      if (!response.ok) throw new Error('Lint failed');

      const data: LintResult = await response.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const filteredIssues = result?.issues.filter((issue) => {
    const matchesType = issueFilter === 'all' || issue.type === issueFilter;
    const matchesSeverity = severityFilter === 'all' || issue.severity === severityFilter;
    return matchesType && matchesSeverity;
  }) || [];

  const severityColor = {
    low: 'text-green-700 bg-green-100',
    medium: 'text-yellow-700 bg-yellow-100',
    high: 'text-red-700 bg-red-100',
  };

  const severityBorder = {
    low: 'border-green-300 bg-green-50',
    medium: 'border-yellow-300 bg-yellow-50',
    high: 'border-red-300 bg-red-50',
  };

  const issueTypeLabel = {
    contradiction: '⚠️ Contradiction',
    orphan: '🔗 Orphan Page',
    broken_link: '❌ Broken Link',
    missing_reference: '🔍 Missing Reference',
    coverage_gap: '📊 Coverage Gap',
    divergence: '↔️ Divergence',
    staleness: '⏰ Stale Content',
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold mb-2">Wiki Health Check</h1>
        <p className="text-gray-600">
          Scan for quality issues and get suggestions for improvement
        </p>
      </div>

      {/* Run Button */}
      <div className="flex items-center gap-4">
        <button
          onClick={runLint}
          disabled={loading}
          className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium flex items-center"
        >
          {loading ? (
            <>
              <span className="inline-block animate-spin mr-2">⟳</span>
              Checking health...
            </>
          ) : (
            '🔎 Run Health Check'
          )}
        </button>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={autoFix}
            onChange={(e) => setAutoFix(e.target.checked)}
            className="rounded"
          />
          <span className="text-sm text-gray-700">Auto-fix issues</span>
        </label>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-600">
          {error}
        </div>
      )}

      {/* Results Summary */}
      {result && (
        <>
          {/* Status Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div
              className={`p-4 rounded-lg border ${
                result.passed
                  ? 'bg-green-50 border-green-200'
                  : 'bg-red-50 border-red-200'
              }`}
            >
              <div className={`text-sm font-medium ${result.passed ? 'text-green-700' : 'text-red-700'}`}>
                Status
              </div>
              <div className={`text-2xl font-bold ${result.passed ? 'text-green-900' : 'text-red-900'}`}>
                {result.passed ? '✓ Healthy' : '✗ Issues'}
              </div>
            </div>

            <div className="p-4 rounded-lg bg-blue-50 border border-blue-200">
              <div className="text-sm font-medium text-blue-700">Issues Found</div>
              <div className="text-2xl font-bold text-blue-900">{result.issues_count}</div>
            </div>

            <div className={`p-4 rounded-lg border ${severityBorder[result.severity]}`}>
              <div className={`text-sm font-medium ${severityColor[result.severity]}`}>Severity</div>
              <div className={`text-2xl font-bold capitalize ${severityColor[result.severity]}`}>
                {result.severity}
              </div>
            </div>

            {result.auto_fixes_applied !== undefined && (
              <div className="p-4 rounded-lg bg-purple-50 border border-purple-200">
                <div className="text-sm font-medium text-purple-700">Auto-Fixed</div>
                <div className="text-2xl font-bold text-purple-900">{result.auto_fixes_applied}</div>
              </div>
            )}
          </div>

          {/* Issue Breakdown by Type */}
          <div className="bg-white border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Issues by Type</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Object.entries(issueTypeLabel).map(([type, label]) => {
                const count = result.issues.filter((i) => i.type === type as any).length;
                return (
                  <button
                    key={type}
                    onClick={() => setIssueFilter(count > 0 ? (type as IssueFilter) : 'all')}
                    className={`p-4 rounded-lg border text-center transition ${
                      issueFilter === type
                        ? 'bg-blue-100 border-blue-500'
                        : count > 0
                        ? 'bg-gray-50 border-gray-300 hover:border-gray-400'
                        : 'bg-gray-50 border-gray-200 opacity-50 cursor-default'
                    }`}
                  >
                    <div className="text-lg">{label.split(' ')[0]}</div>
                    <div className="text-2xl font-bold mt-1">{count}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Issues List */}
          <div className="space-y-4">
            <div className="flex gap-2 items-center">
              <h2 className="text-xl font-bold">Issues</h2>
              <button
                onClick={() => setSeverityFilter('all')}
                className={`px-2 py-1 text-xs rounded ${
                  severityFilter === 'all'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                All
              </button>
              {(['high', 'medium', 'low'] as const).map((severity) => (
                <button
                  key={severity}
                  onClick={() => setSeverityFilter(severity)}
                  className={`px-2 py-1 text-xs rounded capitalize ${
                    severityFilter === severity
                      ? severityColor[severity]
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  {severity}
                </button>
              ))}
            </div>

            {filteredIssues.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                {result.issues_count === 0
                  ? 'No issues found! Your wiki is healthy.'
                  : 'No issues match your filters.'}
              </div>
            ) : (
              <div className="space-y-3">
                {filteredIssues.map((issue) => (
                  <div
                    key={issue.id}
                    className={`border rounded-lg overflow-hidden ${
                      severityBorder[issue.severity]
                    }`}
                  >
                    <button
                      onClick={() =>
                        setExpandedIssue(expandedIssue === issue.id ? null : issue.id)
                      }
                      className="w-full px-6 py-4 flex items-start justify-between hover:bg-black hover:bg-opacity-[0.02] transition text-left"
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`px-2 py-1 rounded text-xs font-medium ${
                              severityColor[issue.severity]
                            }`}
                          >
                            {issue.severity}
                          </span>
                          <span className="font-semibold">{issue.title}</span>
                        </div>
                        <p className="text-sm text-gray-600">{issue.description}</p>
                      </div>
                      <span className="text-gray-400 ml-4">
                        {expandedIssue === issue.id ? '▼' : '▶'}
                      </span>
                    </button>

                    {/* Expanded Details */}
                    {expandedIssue === issue.id && (
                      <div className="px-6 py-4 border-t bg-opacity-50 space-y-4">
                        {issue.affected_pages.length > 0 && (
                          <div>
                            <h4 className="font-medium text-sm mb-2">Affected Pages</h4>
                            <div className="space-y-1">
                              {issue.affected_pages.map((page, idx) => (
                                <div key={idx} className="text-sm text-gray-700">
                                  • {page}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {issue.suggestion && (
                          <div className="bg-white p-3 rounded border-l-4 border-blue-500">
                            <h4 className="font-medium text-sm mb-1">Suggestion</h4>
                            <p className="text-sm text-gray-700">{issue.suggestion}</p>
                          </div>
                        )}

                        <div className="flex gap-2 pt-2">
                          <button className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
                            ✓ Resolve
                          </button>
                          <button className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
                            ⊘ Ignore
                          </button>
                          <button className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
                            ✎ Edit
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Suggestions */}
          {result.suggestions.length > 0 && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
              <h3 className="font-semibold text-blue-900 mb-4">Recommendations</h3>
              <div className="space-y-3">
                {result.suggestions.map((suggestion, idx) => (
                  <div key={idx} className="flex gap-3 text-sm text-blue-800">
                    <span className="text-blue-600 font-bold flex-shrink-0">→</span>
                    <span>{suggestion}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Timestamp */}
          <div className="text-xs text-gray-500 text-center">
            Last checked: {new Date(result.timestamp).toLocaleString()}
          </div>
        </>
      )}

      {/* Help Box */}
      {!result && !loading && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h3 className="font-semibold text-blue-900 mb-3">About Wiki Health Checks</h3>
          <div className="text-sm text-blue-800 space-y-2">
            <p>
              Health checks scan your wiki for seven types of issues:
            </p>
            <ul className="space-y-1 list-disc list-inside">
              <li><strong>Contradictions:</strong> Conflicting claims across pages</li>
              <li><strong>Orphan Pages:</strong> Pages with no incoming links</li>
              <li><strong>Broken Links:</strong> References to non-existent pages</li>
              <li><strong>Missing References:</strong> Concepts mentioned but no dedicated page</li>
              <li><strong>Coverage Gaps:</strong> Important topics under-covered</li>
              <li><strong>Divergence:</strong> Project wiki differs from leading practices</li>
              <li><strong>Staleness:</strong> Pages not updated despite newer sources</li>
            </ul>
            <p className="mt-3">
              Enable auto-fix to automatically resolve low-risk issues like formatting and broken links.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

export default WikiLint;
