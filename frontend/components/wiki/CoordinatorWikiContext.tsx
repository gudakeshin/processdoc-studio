"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * CoordinatorWikiContext - Wiki context integration in Coordinator
 *
 * Shows relevant wiki pages during run planning
 * Provides learnings from similar past runs
 * Displays best practices from leading practice wiki
 */

import React, { useState, useEffect } from 'react';
import Link from 'next/link';

interface ContextPage {
  id: string;
  title: string;
  category: string;
  confidence: string;
  context_type: 'learning' | 'practice' | 'template';
  relevance_score: number;
  snippet: string;
}

interface CoordinatorWikiContextProps {
  projectId: string;
  runObjective: string;
  runType?: string;
}

export const CoordinatorWikiContext: React.FC<CoordinatorWikiContextProps> = ({
  projectId,
  runObjective,
  runType,
}) => {
  const { api } = useAuth();
  const [context, setContext] = useState<ContextPage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const fetchContext = async () => {
      try {
        setLoading(true);
        const params = new URLSearchParams({
          question: runObjective,
          project_id: projectId,
        });

        if (runType) params.append('run_type', runType);

        const response = await api(
          `/api/wiki/project/context?${params.toString()}`,
          { method: 'GET' }
        );

        if (!response.ok) throw new Error('Failed to load context');

        const data = await response.json();
        setContext(data.relevant_pages || []);
      } catch (err) {
        console.error('Error loading context:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    if (runObjective.trim()) {
      fetchContext();
    } else {
      setLoading(false);
    }
  }, [projectId, runObjective, runType, api]);

  if (loading) {
    return (
      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <div className="text-sm text-blue-700 flex items-center">
          <span className="inline-block animate-spin mr-2">⟳</span>
          Loading relevant wiki context...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
        Error loading context
      </div>
    );
  }

  if (context.length === 0) {
    return (
      <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600">
        No relevant wiki pages found for this run
      </div>
    );
  }

  const contextTypeIcon = {
    learning: '💡',
    practice: '⭐',
    template: '📋',
  };

  const contextTypeLabel = {
    learning: 'Learning from Project',
    practice: 'Best Practice',
    template: 'Template',
  };

  // Group by type
  const grouped = context.reduce(
    (acc, page) => {
      if (!acc[page.context_type]) {
        acc[page.context_type] = [];
      }
      acc[page.context_type].push(page);
      return acc;
    },
    {} as Record<string, ContextPage[]>
  );

  return (
    <div className="space-y-4">
      {/* Relevant Pages */}
      {Object.entries(grouped).map(([type, pages]) => (
        <div key={type} className="border rounded-lg overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b">
            <h4 className="font-semibold text-sm">
              {contextTypeIcon[type as keyof typeof contextTypeIcon]}{' '}
              {contextTypeLabel[type as keyof typeof contextTypeLabel]}
            </h4>
          </div>

          <div className="divide-y">
            {pages.map((page) => (
              <div key={page.id}>
                <button
                  onClick={() => setExpanded(expanded === page.id ? null : page.id)}
                  className="w-full px-4 py-3 text-left hover:bg-gray-50 transition flex items-start justify-between gap-2"
                >
                  <div className="flex-1">
                    <div className="font-medium text-blue-600 hover:underline text-sm">
                      {page.title}
                    </div>
                    <div className="flex gap-2 mt-1 items-center">
                      <span className="text-xs bg-gray-100 px-2 py-0.5 rounded capitalize">
                        {page.category}
                      </span>
                      {page.confidence && (
                        <span
                          className={`text-xs px-2 py-0.5 rounded font-medium ${
                            page.confidence === 'high'
                              ? 'bg-green-100 text-green-700'
                              : page.confidence === 'medium'
                              ? 'bg-yellow-100 text-yellow-700'
                              : 'bg-red-100 text-red-700'
                          }`}
                        >
                          {page.confidence}
                        </span>
                      )}
                      <div className="ml-auto text-xs text-gray-500">
                        {Math.round(page.relevance_score * 100)}% match
                      </div>
                    </div>
                  </div>
                  <span className="text-gray-400 flex-shrink-0">
                    {expanded === page.id ? '▼' : '▶'}
                  </span>
                </button>

                {/* Expanded Detail */}
                {expanded === page.id && (
                  <div className="px-4 py-3 bg-gray-50 border-t text-sm">
                    <p className="text-gray-700 mb-3 line-clamp-3">
                      {page.snippet}
                    </p>

                    <div className="flex gap-2">
                      <Link href={`/projects/${projectId}/wiki/pages/${page.id}`} className="flex-1 px-3 py-1 bg-blue-600 text-white rounded text-xs text-center font-medium hover:bg-blue-700 transition">
                          View Full Page
                      </Link>
                      <button className="flex-1 px-3 py-1 border border-gray-300 rounded text-xs text-center font-medium hover:bg-gray-100 transition">
                        📌 Add to Plan
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* Quick Help */}
      <div className="p-3 bg-blue-50 border border-blue-200 rounded text-xs text-blue-700">
        <strong>💡 Tip:</strong> These pages are automatically selected based on your run objective. Click to expand and add relevant pages to your run plan.
      </div>
    </div>
  );
};

export default CoordinatorWikiContext;
