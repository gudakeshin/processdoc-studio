/**
 * WikiQuery - Question answering interface for wiki
 *
 * Features:
 * - Question input form
 * - Answer synthesis with citations
 * - Optional QA evaluation
 * - Source page references
 * - Related questions suggestions
 */

import React, { useState } from 'react';
import Link from 'next/link';

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

export const WikiQuery: React.FC<WikiQueryProps> = ({
  wikiType,
  projectId,
  initialQuestion = '',
}) => {
  const [question, setQuestion] = useState(initialQuestion);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [includeQA, setIncludeQA] = useState(false);
  const [queryHistory, setQueryHistory] = useState<QueryResult[]>([]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const params = new URLSearchParams({
        include_qa: includeQA.toString(),
      });

      if (projectId) params.append('project_id', projectId);

      const response = await fetch(
        `/api/wiki/${wikiType}/query?${params.toString()}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question }),
        }
      );

      if (!response.ok) throw new Error('Query failed');

      const data: QueryResult = await response.json();
      setResult(data);
      setQueryHistory([data, ...queryHistory.slice(0, 4)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleRelatedQuestion = (relatedQ: string) => {
    setQuestion(relatedQ);
  };

  const confidenceColor = {
    high: 'text-green-700 bg-green-100',
    medium: 'text-yellow-700 bg-yellow-100',
    low: 'text-red-700 bg-red-100',
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold mb-2">Ask Wiki</h1>
        <p className="text-gray-600">
          Ask questions and get answers synthesized from {wikiType === 'leading_practice' ? 'leading practices' : 'project'} wiki
        </p>
      </div>

      {/* Query Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Your Question
          </label>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask anything about the wiki... e.g., 'What are the best practices for financial modeling?' or 'How should we approach process redesign?'"
            className="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 h-24 resize-none"
          />
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="includeQA"
            checked={includeQA}
            onChange={(e) => setIncludeQA(e.target.checked)}
            className="rounded"
          />
          <label htmlFor="includeQA" className="text-sm text-gray-700">
            Include quality evaluation
          </label>
        </div>

        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium flex items-center justify-center"
        >
          {loading ? (
            <>
              <span className="inline-block animate-spin mr-2">⟳</span>
              Searching wiki...
            </>
          ) : (
            '🔍 Ask'
          )}
        </button>
      </form>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-600">
          {error}
        </div>
      )}

      {/* Query Result */}
      {result && (
        <div className="space-y-6">
          {/* Answer Box */}
          <div className="bg-white border rounded-lg p-6 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <h2 className="text-2xl font-semibold">Answer</h2>
              <span
                className={`px-3 py-1 rounded text-sm font-medium capitalize ${
                  confidenceColor[result.confidence]
                }`}
              >
                {result.confidence}
              </span>
            </div>

            <p className="text-gray-800 leading-relaxed whitespace-pre-wrap">
              {result.answer}
            </p>

            {/* Citations */}
            {result.citations.length > 0 && (
              <div className="border-t pt-4 mt-4">
                <h3 className="font-semibold mb-3">Sources</h3>
                <div className="space-y-3">
                  {result.citations.map((citation, idx) => (
                    <div key={idx} className="bg-gray-50 p-3 rounded border-l-4 border-blue-500">
                      <div className="font-medium text-blue-600 mb-1">
                        <Link href={`/wiki/${wikiType}/pages/${citation.page_id}`} className="hover:underline">{citation.page_title}</Link>
                      </div>
                      <p className="text-sm text-gray-700 line-clamp-2">
                        {citation.context}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* QA Evaluation */}
            {result.qa_result && (
              <div className="border-t pt-4 mt-4 space-y-3">
                <h3 className="font-semibold">Quality Evaluation</h3>

                <div className="flex items-center gap-3">
                  <div className="text-3xl font-bold text-blue-600">
                    {Math.round(result.qa_result.quality_score)}%
                  </div>
                  <div className="text-sm text-gray-600">
                    <div className="font-medium">Quality Score</div>
                    <div className="text-xs">Based on answer completeness and citations</div>
                  </div>
                </div>

                {result.qa_result.issues.length > 0 && (
                  <div className="bg-yellow-50 border border-yellow-200 p-3 rounded">
                    <div className="font-medium text-yellow-900 mb-2">Potential Issues:</div>
                    <ul className="text-sm text-yellow-800 space-y-1">
                      {result.qa_result.issues.map((issue, idx) => (
                        <li key={idx}>• {issue}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {result.qa_result.suggestions.length > 0 && (
                  <div className="bg-blue-50 border border-blue-200 p-3 rounded">
                    <div className="font-medium text-blue-900 mb-2">Suggestions:</div>
                    <ul className="text-sm text-blue-800 space-y-1">
                      {result.qa_result.suggestions.map((suggestion, idx) => (
                        <li key={idx}>• {suggestion}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Related Questions */}
          {result.related_questions && result.related_questions.length > 0 && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
              <h3 className="font-semibold mb-3">Related Questions</h3>
              <div className="space-y-2">
                {result.related_questions.map((relatedQ, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleRelatedQuestion(relatedQ)}
                    className="w-full text-left p-3 bg-white border rounded hover:bg-blue-50 transition"
                  >
                    <div className="text-blue-600 font-medium hover:underline">
                      {relatedQ}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Save/Share Actions */}
          <div className="flex gap-2">
            <button className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium text-sm">
              💾 Save Question
            </button>
            <button className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium text-sm">
              📤 Share Answer
            </button>
            <button className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium text-sm">
              ✎ Edit Answer
            </button>
          </div>
        </div>
      )}

      {/* Query History */}
      {queryHistory.length > 0 && !result && (
        <div className="bg-gray-50 border rounded-lg p-6">
          <h3 className="font-semibold mb-4">Recent Questions</h3>
          <div className="space-y-2">
            {queryHistory.slice(0, 3).map((item, idx) => (
              <button
                key={idx}
                onClick={() => handleRelatedQuestion(item.question)}
                className="w-full text-left p-3 bg-white border rounded hover:bg-blue-50 transition"
              >
                <div className="text-gray-900 font-medium">{item.question}</div>
                <div className="text-xs text-gray-500 mt-1">
                  {item.citations.length} source{item.citations.length !== 1 ? 's' : ''}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Help Box */}
      {!result && !question && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h3 className="font-semibold text-blue-900 mb-3">How to Ask Good Questions</h3>
          <ul className="text-sm text-blue-800 space-y-2 list-disc list-inside">
            <li>Be specific about what you want to know</li>
            <li>Include context if needed (e.g., "for financial modeling")</li>
            <li>Ask about practices, frameworks, decisions, or outcomes</li>
            <li>Enable quality evaluation for critical decisions</li>
            <li>Check related questions for alternative phrasings</li>
          </ul>
        </div>
      )}
    </div>
  );
};

export default WikiQuery;
