"use client";

import { useAuth } from '@/lib/auth-context';
/**
 * WikiArtifactSection - Wiki artifact display in Run Studio
 *
 * Shows run artifacts and wiki pages created from this run
 * Provides links between run outputs and wiki pages
 */

import React, { useState, useEffect } from 'react';
import Link from 'next/link';

interface WikiArtifact {
  id: string;
  name: string;
  type: string;
  created_from_page_id?: string;
  page_title?: string;
  category: string;
  created_at: string;
}

interface WikiArtifactSectionProps {
  runId: string;
  projectId: string;
  runName?: string;
}

export const WikiArtifactSection: React.FC<WikiArtifactSectionProps> = ({
  runId,
  projectId,
  runName = 'Run',
}) => {
  const { api } = useAuth();
  const [artifacts, setArtifacts] = useState<WikiArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchArtifacts = async () => {
      try {
        setLoading(true);
        const response = await api(
          `/api/wiki/project/artifacts?run_id=${runId}&project_id=${projectId}`,
          { method: 'GET' }
        );

        if (!response.ok) throw new Error('Failed to load artifacts');

        const data = await response.json();
        setArtifacts(data.artifacts || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchArtifacts();
  }, [runId, projectId]);

  if (loading) {
    return <div className="p-4 text-center text-gray-500">Loading artifacts...</div>;
  }

  if (error) {
    return <div className="p-4 text-red-600">Error: {error}</div>;
  }

  if (artifacts.length === 0) {
    return (
      <div className="p-4 text-center text-gray-500">
        <p>No wiki artifacts from this run yet</p>
        <p className="text-sm mt-2">
          <Link href={`/projects/${projectId}/wiki?tab=ingest`} className="text-blue-600 hover:underline">Add sources to wiki →</Link>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-semibold text-lg mb-4">Wiki Artifacts from {runName}</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {artifacts.map((artifact) => (
            <Link
              key={artifact.id}
              href={`/projects/${projectId}/wiki/pages/${artifact.created_from_page_id || artifact.id}`}
              className="p-4 border rounded-lg hover:shadow-md transition bg-white"
            >
                <div className="flex items-start justify-between mb-2">
                  <h4 className="font-semibold text-blue-600 hover:underline flex-1">
                    {artifact.page_title || artifact.name}
                  </h4>
                  <span className="text-xs bg-gray-100 px-2 py-1 rounded capitalize flex-shrink-0">
                    {artifact.type}
                  </span>
                </div>

                <div className="text-xs text-gray-600 mb-2">
                  <span className="capitalize">{artifact.category}</span>
                  {' • '}
                  {new Date(artifact.created_at).toLocaleDateString()}
                </div>

                <div className="text-sm text-gray-600">
                  {artifact.created_from_page_id ? (
                    <span className="text-green-600">
                      ✓ Ingested to wiki
                    </span>
                  ) : (
                    <span className="text-gray-500">
                      Created from run
                    </span>
                  )}
                </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="flex gap-2 pt-4 border-t">
        <Link href={`/projects/${projectId}/wiki?tab=ingest`} className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-center font-medium text-sm">
            ⬆️ Ingest More Sources
        </Link>
        <Link href={`/projects/${projectId}/wiki?tab=browse`} className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 text-center font-medium text-sm">
            📖 Browse All
        </Link>
      </div>
    </div>
  );
};

export default WikiArtifactSection;
