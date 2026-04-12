/**
 * WikiPage - Single page display with metadata, content, and related pages
 *
 * Features:
 * - Full page content with markdown rendering
 * - Metadata display (category, confidence, dates, links)
 * - Related pages and cross-references
 * - Action buttons (edit, promote, etc.)
 * - Breadcrumb navigation
 */

import React, { useState, useEffect } from 'react';
import Link from 'next/link';

interface PageLink {
  id: string;
  title: string;
  type: 'inbound' | 'outbound';
}

interface PageMetadata {
  id: string;
  title: string;
  category: string;
  confidence: string;
  content: string;
  created_at: string;
  updated_at: string;
  created_by?: string;
  source_memory_ids?: string[];
  source_run_ids?: string[];
  inbound_links: PageLink[];
  outbound_links: PageLink[];
  pages_linking_count: number;
  frontmatter: Record<string, any>;
}

interface WikiPageProps {
  wikiType: 'leading_practice' | 'project';
  pageId: string;
  projectId?: string;
}

export const WikiPage: React.FC<WikiPageProps> = ({
  wikiType,
  pageId,
  projectId,
}) => {
  const [page, setPage] = useState<PageMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'content' | 'links' | 'metadata'>('content');

  useEffect(() => {
    const fetchPage = async () => {
      try {
        setLoading(true);
        setError(null);

        const params = new URLSearchParams();
        if (projectId) params.append('project_id', projectId);

        const response = await fetch(
          `/api/wiki/${wikiType}/pages/${pageId}?${params.toString()}`,
          { method: 'GET' }
        );

        if (!response.ok) throw new Error('Failed to load page');

        const data = await response.json();
        setPage(data.page);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchPage();
  }, [wikiType, pageId, projectId]);

  if (loading) {
    return <div className="p-8 text-center">Loading page...</div>;
  }

  if (error) {
    return <div className="p-8 text-red-600">Error: {error}</div>;
  }

  if (!page) {
    return <div className="p-8">Page not found</div>;
  }

  const confidenceColor = {
    high: 'text-green-700 bg-green-100',
    medium: 'text-yellow-700 bg-yellow-100',
    low: 'text-red-700 bg-red-100',
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <Link href={`/wiki/${wikiType}`} className="hover:text-blue-600">{wikiType === 'leading_practice' ? 'Leading Practices' : 'Wiki'}</Link>
        <span>/</span>
        <span className="capitalize">{page.category}</span>
        <span>/</span>
        <span className="font-medium text-gray-900">{page.title}</span>
      </div>

      {/* Header with Title and Metadata */}
      <div className="border-b pb-6">
        <div className="flex items-start justify-between mb-4">
          <h1 className="text-4xl font-bold">{page.title}</h1>
          <span
            className={`px-4 py-2 rounded font-medium text-sm capitalize ${
              confidenceColor[page.confidence as keyof typeof confidenceColor]
            }`}
          >
            {page.confidence} Confidence
          </span>
        </div>

        <div className="flex flex-wrap gap-4 text-sm text-gray-600 mb-4">
          <div>
            <span className="font-medium">Category:</span> <span className="capitalize">{page.category}</span>
          </div>
          <div>
            <span className="font-medium">Updated:</span> {new Date(page.updated_at).toLocaleDateString()}
          </div>
          <div>
            <span className="font-medium">Created:</span> {new Date(page.created_at).toLocaleDateString()}
          </div>
          {page.created_by && (
            <div>
              <span className="font-medium">Source:</span> {page.created_by}
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2 flex-wrap">
          <button className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium">
            ✎ Edit
          </button>
          {wikiType === 'project' && (
            <button className="px-4 py-2 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 text-sm font-medium">
              ↑ Promote to LP
            </button>
          )}
          <button className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 text-sm font-medium">
            ⋮ More
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 border-b">
        {(['content', 'links', 'metadata'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-medium capitalize border-b-2 -mb-1 transition ${
              activeTab === tab
                ? 'text-blue-600 border-blue-600'
                : 'text-gray-600 border-transparent hover:text-gray-900'
            }`}
          >
            {tab === 'content' ? 'Content' : tab === 'links' ? 'Links' : 'Metadata'}
            {tab === 'links' && page.pages_linking_count > 0 && (
              <span className="ml-2 px-2 py-0 bg-gray-200 rounded-full text-xs">
                {page.inbound_links.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Content Tab */}
      {activeTab === 'content' && (
        <div className="prose prose-sm max-w-none">
          <div
            className="bg-white p-6 rounded-lg border"
            dangerouslySetInnerHTML={{
              __html: page.content.replace(/\n/g, '<br/>'),
            }}
          />
        </div>
      )}

      {/* Links Tab */}
      {activeTab === 'links' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Inbound Links */}
          <div>
            <h3 className="font-semibold mb-4 text-lg">Referenced By ({page.inbound_links.length})</h3>
            {page.inbound_links.length === 0 ? (
              <p className="text-gray-500">No pages reference this one yet</p>
            ) : (
              <div className="space-y-2">
                {page.inbound_links.map((link) => (
                  <Link key={link.id} href={`/wiki/${wikiType}/pages/${link.id}`} className="block p-3 border rounded hover:bg-blue-50 transition">
                      <div className="text-blue-600 font-medium hover:underline">{link.title}</div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Outbound Links */}
          <div>
            <h3 className="font-semibold mb-4 text-lg">References ({page.outbound_links.length})</h3>
            {page.outbound_links.length === 0 ? (
              <p className="text-gray-500">This page doesn't reference other pages</p>
            ) : (
              <div className="space-y-2">
                {page.outbound_links.map((link) => (
                  <Link key={link.id} href={`/wiki/${wikiType}/pages/${link.id}`} className="block p-3 border rounded hover:bg-blue-50 transition">
                      <div className="text-blue-600 font-medium hover:underline">{link.title}</div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Metadata Tab */}
      {activeTab === 'metadata' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Frontmatter */}
          <div className="bg-white p-6 rounded-lg border">
            <h3 className="font-semibold mb-4">Frontmatter</h3>
            <div className="space-y-3 text-sm">
              {Object.entries(page.frontmatter).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <span className="font-medium text-gray-600 w-32">{key}:</span>
                  <span className="text-gray-900">
                    {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Sources */}
          <div className="bg-white p-6 rounded-lg border space-y-4">
            {page.source_memory_ids && page.source_memory_ids.length > 0 && (
              <div>
                <h3 className="font-semibold mb-2">Memory Items</h3>
                <div className="space-y-1 text-sm">
                  {page.source_memory_ids.map((id) => (
                    <div key={id} className="text-blue-600 hover:underline cursor-pointer">
                      {id}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {page.source_run_ids && page.source_run_ids.length > 0 && (
              <div>
                <h3 className="font-semibold mb-2">Run Artifacts</h3>
                <div className="space-y-1 text-sm">
                  {page.source_run_ids.map((id) => (
                    <div key={id} className="text-blue-600 hover:underline cursor-pointer">
                      {id}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!page.source_memory_ids && !page.source_run_ids && (
              <p className="text-gray-500 text-sm">No source references</p>
            )}
          </div>
        </div>
      )}

      {/* Back to Browse */}
      <div className="pt-6 border-t">
        <Link href={`/wiki/${wikiType}/browse`} className="text-blue-600 hover:underline font-medium">← Back to Browse</Link>
      </div>
    </div>
  );
};

export default WikiPage;
