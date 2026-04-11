/**
 * WikiIngest - Interface for ingesting new sources into wiki
 *
 * Features:
 * - Source type selector (URL, document, run artifact, conversation)
 * - Type-specific form inputs
 * - Progress tracking during ingest
 * - Results display with corrections and QA summary
 */

import React, { useState } from 'react';

type SourceType = 'url' | 'document' | 'run_artifact' | 'conversation';

interface IngestResult {
  status: 'success' | 'error';
  pages_created?: number;
  pages_updated?: number;
  corrections_made?: number;
  qa_results?: {
    severity: 'low' | 'medium' | 'high';
    issues_count: number;
  };
  error?: string;
}

interface WikiIngestProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

export const WikiIngest: React.FC<WikiIngestProps> = ({
  wikiType,
  projectId,
}) => {
  const [sourceType, setSourceType] = useState<SourceType>('url');
  const [formData, setFormData] = useState<Record<string, string>>({
    url: '',
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sourceTypeConfig = {
    url: {
      label: 'Web URL',
      description: 'Ingest content from a web article or document',
      fields: [{ name: 'url', label: 'URL', type: 'url', placeholder: 'https://example.com/article' }],
    },
    document: {
      label: 'Document',
      description: 'Upload a PDF, Word, or Excel document',
      fields: [{ name: 'filename', label: 'File', type: 'file' }],
    },
    run_artifact: {
      label: 'Run Artifact',
      description: 'Capture learnings from a completed run',
      fields: [{ name: 'run_id', label: 'Run ID', type: 'text' }],
    },
    conversation: {
      label: 'Conversation',
      description: 'Digest a conversation into wiki knowledge',
      fields: [{ name: 'conversation_id', label: 'Conversation ID', type: 'text' }],
    },
  };

  const config = sourceTypeConfig[sourceType];

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const sourceData: Record<string, any> = {};

      if (sourceType === 'url') {
        sourceData.url = formData.url;
      } else if (sourceType === 'document') {
        sourceData.filename = formData.filename;
      } else if (sourceType === 'run_artifact') {
        sourceData.run_id = formData.run_id;
      } else if (sourceType === 'conversation') {
        sourceData.conversation_id = formData.conversation_id;
      }

      const params = new URLSearchParams({
        source_type: sourceType,
      });

      if (projectId) params.append('project_id', projectId);

      const response = await fetch(
        `/api/wiki/${wikiType}/ingest?${params.toString()}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source_data: sourceData }),
        }
      );

      if (!response.ok) throw new Error('Ingest failed');

      const data: IngestResult = await response.json();
      setResult(data);

      if (data.status === 'success') {
        setFormData({ url: '' });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">Ingest Source</h1>
        <p className="text-gray-600 mt-2">
          Add new sources to the wiki with automatic knowledge capture
        </p>
      </div>

      {/* Source Type Selector */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">What are you adding?</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Object.entries(sourceTypeConfig).map(([type, config]) => (
            <label
              key={type}
              className={`p-4 border-2 rounded-lg cursor-pointer transition ${
                sourceType === type
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <input
                type="radio"
                name="sourceType"
                value={type}
                checked={sourceType === type}
                onChange={() => setSourceType(type as SourceType)}
                className="mr-3"
              />
              <span className="font-semibold">{config.label}</span>
              <p className="text-sm text-gray-600 mt-1">{config.description}</p>
            </label>
          ))}
        </div>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        {config.fields.map((field) => (
          <div key={field.name}>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {field.label}
            </label>
            {field.type === 'file' ? (
              <input
                type="file"
                name={field.name}
                accept=".pdf,.doc,.docx,.xlsx"
                onChange={handleInputChange}
                className="w-full px-4 py-2 border rounded-lg"
                required
              />
            ) : (
              <input
                type={field.type}
                name={field.name}
                value={formData[field.name] || ''}
                onChange={handleInputChange}
                placeholder={field.placeholder}
                className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              />
            )}
          </div>
        ))}

        {error && (
          <div className="p-4 bg-red-50 border border-red-200 rounded text-red-600">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
        >
          {loading ? (
            <>
              <span className="inline-block animate-spin mr-2">⟳</span>
              Ingesting...
            </>
          ) : (
            'Ingest Source'
          )}
        </button>
      </form>

      {/* Results */}
      {result && (
        <div
          className={`p-6 rounded-lg border ${
            result.status === 'success'
              ? 'bg-green-50 border-green-200'
              : 'bg-red-50 border-red-200'
          }`}
        >
          {result.status === 'success' ? (
            <div>
              <h3 className="font-semibold text-green-900 mb-4">✓ Ingest Complete</h3>

              <div className="grid grid-cols-3 gap-4 mb-6">
                <div>
                  <div className="text-2xl font-bold text-green-600">
                    {result.pages_created || 0}
                  </div>
                  <div className="text-sm text-green-700">Pages Created</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-blue-600">
                    {result.corrections_made || 0}
                  </div>
                  <div className="text-sm text-blue-700">Corrections Made</div>
                </div>
                <div>
                  <div
                    className={`text-2xl font-bold ${
                      result.qa_results?.severity === 'high'
                        ? 'text-red-600'
                        : result.qa_results?.severity === 'medium'
                        ? 'text-yellow-600'
                        : 'text-green-600'
                    }`}
                  >
                    {result.qa_results?.issues_count || 0}
                  </div>
                  <div className="text-sm text-gray-700">QA Issues</div>
                </div>
              </div>

              <div className="space-y-3">
                <h4 className="font-medium text-gray-900">What happened:</h4>
                <ul className="text-sm text-gray-700 space-y-2">
                  <li>✓ Source parsed and extracted</li>
                  <li>✓ Wiki pages created with metadata</li>
                  <li>✓ Data quality issues auto-corrected</li>
                  <li>✓ Health check completed</li>
                </ul>
              </div>

              {result.corrections_made! > 0 && (
                <div className="mt-4 p-3 bg-blue-100 border border-blue-300 rounded text-blue-900 text-sm">
                  <strong>{result.corrections_made} correction(s)</strong> were automatically applied:
                  <ul className="mt-2 space-y-1 text-xs list-disc list-inside">
                    <li>Fixed missing frontmatter fields</li>
                    <li>Normalized formatting</li>
                    <li>Validated data types</li>
                  </ul>
                </div>
              )}

              {result.qa_results && result.qa_results.issues_count > 0 && (
                <div className="mt-4 p-3 bg-yellow-100 border border-yellow-300 rounded text-yellow-900 text-sm">
                  <strong>{result.qa_results.issues_count} quality issue(s)</strong> detected.
                  <a href="#" className="block text-blue-600 hover:underline mt-2">
                    View details and suggestions →
                  </a>
                </div>
              )}
            </div>
          ) : (
            <div>
              <h3 className="font-semibold text-red-900 mb-2">✗ Ingest Failed</h3>
              <p className="text-red-700">{result.error}</p>
            </div>
          )}
        </div>
      )}

      {/* Info Box */}
      <div className="p-4 bg-blue-50 border border-blue-200 rounded">
        <h4 className="font-semibold text-blue-900 mb-2">How it works:</h4>
        <ol className="text-sm text-blue-800 space-y-2 list-decimal list-inside">
          <li>Your source is parsed and key information extracted</li>
          <li>Wiki pages are automatically created with proper metadata</li>
          <li>Data quality issues (formatting, type mismatches) are auto-corrected</li>
          <li>Health checks detect potential problems</li>
          <li>Pages are ready to search and link immediately</li>
        </ol>
      </div>
    </div>
  );
};

export default WikiIngest;
