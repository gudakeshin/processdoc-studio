/**
 * WikiMemoryLink - Links memory items to wiki pages
 *
 * Shows wiki pages created from a memory item
 * Enables creating new wiki pages from memory
 */

import React, { useState, useEffect } from 'react';
import Link from 'next/link';

interface LinkedPage {
  id: string;
  title: string;
  category: string;
  confidence: string;
}

interface WikiMemoryLinkProps {
  memoryId: string;
  memoryType: 'fact' | 'decision' | 'constraint';
  memoryContent: string;
  projectId: string;
}

export const WikiMemoryLink: React.FC<WikiMemoryLinkProps> = ({
  memoryId,
  memoryType,
  memoryContent,
  projectId,
}) => {
  const [linkedPages, setLinkedPages] = useState<LinkedPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);

  useEffect(() => {
    const fetchLinkedPages = async () => {
      try {
        const response = await fetch(
          `/api/wiki/project/memory/${memoryId}/pages?project_id=${projectId}`,
          { method: 'GET' }
        );

        if (!response.ok) throw new Error('Failed to load linked pages');

        const data = await response.json();
        setLinkedPages(data.pages || []);
      } catch (err) {
        console.error('Error loading linked pages:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchLinkedPages();
  }, [memoryId, projectId]);

  const handleCreateWikiPage = async (title: string, category: string) => {
    try {
      const response = await fetch(
        `/api/wiki/project/ingest/from-memory`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            memory_id: memoryId,
            memory_type: memoryType,
            memory_content: memoryContent,
            title,
            category,
            project_id: projectId,
          }),
        }
      );

      if (!response.ok) throw new Error('Failed to create page');

      const data = await response.json();
      setLinkedPages([...linkedPages, data.page]);
      setShowCreateModal(false);
    } catch (err) {
      console.error('Error creating page:', err);
    }
  };

  const typeIcon = {
    fact: '📌',
    decision: '⚡',
    constraint: '🚫',
  };

  const confidenceColor = {
    high: 'text-green-700 bg-green-100',
    medium: 'text-yellow-700 bg-yellow-100',
    low: 'text-red-700 bg-red-100',
  };

  if (loading) {
    return (
      <div className="text-sm text-gray-500">
        Loading wiki links...
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {linkedPages.length > 0 ? (
        <>
          <div>
            <h4 className="text-sm font-semibold mb-2">Wiki Pages</h4>
            <div className="space-y-2">
              {linkedPages.map((page) => (
                <Link
                  key={page.id}
                  href={`/projects/${projectId}/wiki/pages/${page.id}`}
                  className="block p-2 border rounded hover:bg-blue-50 transition text-sm"
                >
                    <div className="font-medium text-blue-600 hover:underline">
                      {page.title}
                    </div>
                    <div className="flex gap-2 mt-1">
                      <span className="text-xs bg-gray-100 px-2 py-0.5 rounded capitalize">
                        {page.category}
                      </span>
                      <span
                        className={`text-xs px-2 py-0.5 rounded capitalize font-medium ${
                          confidenceColor[page.confidence as keyof typeof confidenceColor]
                        }`}
                      >
                        {page.confidence}
                      </span>
                    </div>
                </Link>
              ))}
            </div>
          </div>

          <button
            onClick={() => setShowCreateModal(true)}
            className="w-full text-sm px-3 py-2 border border-gray-300 rounded hover:bg-gray-50 font-medium"
          >
            + Create Additional Wiki Page
          </button>
        </>
      ) : (
        <div className="text-sm text-gray-600 space-y-3">
          <p>
            {typeIcon[memoryType]} This {memoryType} hasn't been added to wiki yet
          </p>

          <button
            onClick={() => setShowCreateModal(true)}
            className="w-full px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
          >
            ⬆️ Create Wiki Page
          </button>
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreateWikiPageModal
          onClose={() => setShowCreateModal(false)}
          onCreate={handleCreateWikiPage}
          memoryType={memoryType}
          defaultContent={memoryContent}
        />
      )}
    </div>
  );
};

interface CreateWikiPageModalProps {
  onClose: () => void;
  onCreate: (title: string, category: string) => void;
  memoryType: string;
  defaultContent: string;
}

const CreateWikiPageModal: React.FC<CreateWikiPageModalProps> = ({
  onClose,
  onCreate,
  memoryType,
  defaultContent,
}) => {
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('entity');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await onCreate(title, category);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-lg p-6 max-w-lg w-full mx-4">
        <h3 className="text-lg font-semibold mb-4">Create Wiki Page</h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Page Title
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Enter page title"
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="entity">Entity</option>
              <option value="concept">Concept</option>
              <option value="decision">Decision</option>
              <option value="learning">Learning</option>
              <option value="template">Template</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Source Content Preview
            </label>
            <div className="bg-gray-50 p-3 rounded text-sm text-gray-700 line-clamp-3">
              {defaultContent}
            </div>
          </div>

          <div className="flex gap-2 justify-end pt-4 border-t">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium disabled:opacity-50"
              disabled={loading || !title.trim()}
            >
              {loading ? 'Creating...' : 'Create Page'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default WikiMemoryLink;
