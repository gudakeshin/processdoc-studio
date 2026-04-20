"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiIngest — ingest new sources into the wiki.
 * Project documents are synced automatically on the Overview tab.
 * Use this to ingest URLs, run artifacts, conversations, or additional documents.
 */

import React, { useState } from 'react';
import { Button } from '@/components/ui/Button';

type SourceType = 'url' | 'document' | 'run_artifact' | 'conversation';

interface IngestResult {
  status: 'success' | 'error';
  pages_created?: number;
  pages_updated?: number;
  corrections_made?: number;
  qa_results?: { severity: 'low' | 'medium' | 'high'; issues_count: number };
  error?: string;
}

interface WikiIngestProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

// All formats the backend supports
const ACCEPTED_FILES = '.txt,.md,.csv,.json,.pdf,.doc,.docx,.pptx,.xlsx,.xls';

const SOURCE_TYPES: { key: SourceType; label: string; description: string; fieldName: string; fieldType: string; placeholder?: string }[] = [
  { key: 'url',          label: 'Web URL',      description: 'Ingest a web article or document',    fieldName: 'url',             fieldType: 'url',  placeholder: 'https://example.com/article' },
  { key: 'document',     label: 'Document',     description: 'Upload PDF, Word, Excel, PowerPoint', fieldName: 'filename',        fieldType: 'file' },
  { key: 'run_artifact', label: 'Run Artifact', description: 'Capture learnings from a run',        fieldName: 'run_id',          fieldType: 'text', placeholder: 'run-abc123' },
  { key: 'conversation', label: 'Conversation', description: 'Digest a conversation',               fieldName: 'conversation_id', fieldType: 'text', placeholder: 'conv-abc123' },
];

export const WikiIngest: React.FC<WikiIngestProps> = ({ wikiType, projectId }) => {
  const { api } = useAuth();
  const [sourceType, setSourceType] = useState<SourceType>('url');
  const [fieldValue, setFieldValue] = useState('');
  const [loading, setLoading]       = useState(false);
  const [result, setResult]         = useState<IngestResult | null>(null);
  const [error, setError]           = useState<string | null>(null);

  const config = SOURCE_TYPES.find((s) => s.key === sourceType)!;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      let finalFieldValue = fieldValue;

      if (config.fieldType === 'file') {
        if (!projectId) throw new Error('Project ID required for document upload');
        const fileInput = (e.target as HTMLFormElement).querySelector('input[type="file"]') as HTMLInputElement;
        const file = fileInput?.files?.[0];
        if (!file) throw new Error('No file selected');

        const formData = new FormData();
        formData.append('project_id', projectId);
        formData.append('file', file);

        const uploadRes = await api('/api/documents/upload', {
          method: 'POST',
          body: formData,
        });
        if (!uploadRes.ok) throw new Error('File upload failed');
        const uploadData = await uploadRes.json();
        finalFieldValue = uploadData.filename || file.name;
      }

      const sourceData: Record<string, string> = { [config.fieldName]: finalFieldValue };
      const params = new URLSearchParams({ source_type: sourceType });
      if (projectId) params.append('project_id', projectId);

      const res = await api(`/api/wiki/${wikiType}/ingest?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_data: sourceData }),
      });
      if (!res.ok) throw new Error('Ingest failed');
      const data: IngestResult = await res.json();
      setResult(data);
      if (data.status === 'success') {
        setFieldValue('');
        (e.target as HTMLFormElement).reset();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-xl space-y-5">
      {/* Source type selector */}
      <div className="grid grid-cols-2 gap-2">
        {SOURCE_TYPES.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => { setSourceType(s.key); setFieldValue(''); setResult(null); }}
            className={`px-3 py-2.5 border text-left transition ${
              sourceType === s.key
                ? 'border-[var(--accent-blue)] bg-[var(--surface-muted)]'
                : 'border-[var(--surface-border)] hover:border-[var(--text-default)]'
            }`}
          >
            <div className="text-xs font-medium text-[var(--text-default)]">{s.label}</div>
            <div className="text-[10px] text-[var(--text-muted)] mt-0.5">{s.description}</div>
          </button>
        ))}
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
            {config.label}
          </label>
          {config.fieldType === 'file' ? (
            <input
              key={`file-${sourceType}`}
              type="file"
              accept={ACCEPTED_FILES}
              onChange={(e) => setFieldValue(e.target.files?.[0]?.name || '')}
              className="w-full text-sm text-[var(--text-default)] border border-[var(--surface-border)] px-3 py-2 bg-white file:mr-3 file:border-0 file:bg-[var(--surface-muted)] file:px-2 file:py-1 file:text-xs"
              required
            />
          ) : (
            <input
              type={config.fieldType}
              value={fieldValue}
              onChange={(e) => setFieldValue(e.target.value)}
              placeholder={config.placeholder}
              className="w-full px-3 py-2 text-sm border border-[var(--surface-border)] bg-white text-[var(--text-default)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-blue)]"
              required
            />
          )}
        </div>

        {error && <p className="text-xs text-[var(--error)]">{error}</p>}

        <Button type="submit" variant="primary" className="w-full text-xs py-2" disabled={loading}>
          {loading ? 'Ingesting…' : 'Ingest Source'}
        </Button>
      </form>

      {/* Result */}
      {result && result.status === 'success' && (
        <div className="border border-[var(--surface-border)] divide-y divide-[var(--surface-border)]">
          <div className="px-4 py-2 bg-[var(--surface-muted)]">
            <span className="text-xs font-medium text-[var(--success)]">Ingest complete</span>
          </div>
          <div className="grid grid-cols-3 divide-x divide-[var(--surface-border)]">
            {[
              { label: 'Created',     value: result.pages_created    ?? 0 },
              { label: 'Corrections', value: result.corrections_made ?? 0 },
              { label: 'QA Issues',   value: result.qa_results?.issues_count ?? 0 },
            ].map(({ label, value }) => (
              <div key={label} className="px-4 py-3 bg-[var(--surface-muted)]">
                <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{label}</div>
                <div className="text-lg font-semibold text-[var(--text-default)] mt-0.5">{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {result && result.status === 'error' && (
        <p className="text-xs text-[var(--error)]">Ingest failed: {result.error}</p>
      )}

      {/* Info */}
      {!result && (
        <div className="border border-[var(--surface-border)] px-4 py-3 bg-[var(--surface-muted)]">
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1.5">Note</p>
          <p className="text-xs text-[var(--text-muted)]">
            Documents uploaded in Run Studio are added to the wiki automatically.
            Use this tab to ingest URLs, run artifacts, conversations, or extra documents.
          </p>
        </div>
      )}
    </div>
  );
};

export default WikiIngest;
