"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiQuery — question answering interface.
 */

import React, { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { confidenceClass } from '@/utils/wikiColors';

interface Citation {
  page_id: string;
  page_title: string;
  context: string;
}

interface QueryResult {
  status: 'success' | 'error';
  question: string;
  answer: string;
  citations: Citation[];
  source_pages: string[];
  confidence: 'high' | 'medium' | 'low';
  qa_result?: {
    quality_score: number;
    issues: string[];
    suggestions: string[];
  };
  related_questions?: string[];
  error?: string;
}

interface WikiQueryProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
  initialQuestion?: string;
}

export const WikiQuery: React.FC<WikiQueryProps> = ({ wikiType, projectId, initialQuestion = '' }) => {
  const { api } = useAuth();
  const [question, setQuestion]   = useState(initialQuestion);
  const [result, setResult]       = useState<QueryResult | null>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [includeQA, setIncludeQA] = useState(false);
  const [history, setHistory]     = useState<QueryResult[]>([]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const params = new URLSearchParams({ include_qa: includeQA.toString() });
      if (projectId) params.append('project_id', projectId);
      const res = await api(`/api/wiki/${wikiType}/query?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) throw new Error('Query failed');
      const data: QueryResult = await res.json();
      setResult(data);
      setHistory((prev) => [data, ...prev.slice(0, 4)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-3">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={`Ask anything about the ${wikiType === 'leading_practice' ? 'leading practices' : 'project'} wiki…`}
          className="w-full px-3 py-2 text-sm border border-[var(--surface-border)] bg-white text-[var(--text-default)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-blue)] h-20 resize-none"
        />
        <div className="flex items-center justify-between gap-3">
          <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] cursor-pointer">
            <input type="checkbox" checked={includeQA} onChange={(e) => setIncludeQA(e.target.checked)} />
            Quality evaluation
          </label>
          <Button type="submit" variant="primary" className="text-xs px-4 py-2" disabled={loading || !question.trim()}>
            {loading ? 'Searching…' : 'Ask'}
          </Button>
        </div>
      </form>

      {error && <p className="text-xs text-[var(--error)]">{error}</p>}

      {/* Result */}
      {result && (
        <div className="space-y-4">
          {/* Answer */}
          <div className="border border-[var(--surface-border)]">
            <div className="flex items-center justify-between px-4 py-2 bg-[var(--surface-muted)] border-b border-[var(--surface-border)]">
              <span className="text-xs font-medium text-[var(--text-default)]">Answer</span>
              <span className={`inline-flex items-center px-2 py-0.5 text-[10px] border capitalize ${confidenceClass[result.confidence] ?? confidenceClass.medium}`}>
                {result.confidence} confidence
              </span>
            </div>
            <div className="px-4 py-3 text-sm text-[var(--text-default)] leading-relaxed whitespace-pre-wrap">
              {result.answer}
            </div>

            {/* Citations */}
            {result.citations.length > 0 && (
              <div className="border-t border-[var(--surface-border)] px-4 py-3">
                <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-2">Sources</p>
                <div className="space-y-2">
                  {result.citations.map((c, i) => (
                    <div key={i} className="border-l-2 border-[var(--accent-blue)] pl-3">
                      <div className="text-xs font-medium text-[var(--accent-blue)]">{c.page_title}</div>
                      <p className="text-xs text-[var(--text-muted)] line-clamp-2 mt-0.5">{c.context}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* QA */}
            {result.qa_result && (
              <div className="border-t border-[var(--surface-border)] px-4 py-3 space-y-2">
                <div className="flex items-center gap-3">
                  <span className="text-lg font-semibold text-[var(--accent-blue)]">{Math.round(result.qa_result.quality_score)}%</span>
                  <span className="text-xs text-[var(--text-muted)]">Quality score</span>
                </div>
                {result.qa_result.issues.length > 0 && (
                  <ul className="text-xs text-[var(--warning)] space-y-0.5">
                    {result.qa_result.issues.map((issue, i) => <li key={i}>· {issue}</li>)}
                  </ul>
                )}
                {result.qa_result.suggestions.length > 0 && (
                  <ul className="text-xs text-[var(--text-muted)] space-y-0.5">
                    {result.qa_result.suggestions.map((s, i) => <li key={i}>→ {s}</li>)}
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* Related questions */}
          {(result.related_questions ?? []).length > 0 && (
            <div>
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1.5">Related</p>
              <div className="space-y-1">
                {result.related_questions!.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => setQuestion(q)}
                    className="w-full text-left text-xs text-[var(--accent-blue)] px-3 py-1.5 border border-[var(--surface-border)] hover:bg-[var(--surface-muted)] transition"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* History */}
      {!result && history.length > 0 && (
        <div>
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1.5">Recent</p>
          <div className="space-y-1">
            {history.slice(0, 3).map((item, i) => (
              <button
                key={i}
                onClick={() => setQuestion(item.question)}
                className="w-full text-left text-xs px-3 py-1.5 border border-[var(--surface-border)] hover:bg-[var(--surface-muted)] transition"
              >
                <span className="text-[var(--text-default)]">{item.question}</span>
                <span className="text-[var(--text-muted)] ml-2">· {item.citations.length} source{item.citations.length !== 1 ? 's' : ''}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default WikiQuery;
