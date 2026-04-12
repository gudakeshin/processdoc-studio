/**
 * WikiDashboard - Main wiki interface with overview, search, and actions
 *
 * Displays:
 * - Wiki statistics (total pages, by category)
 * - Health summary (issues, severity)
 * - Quick actions (search, ingest, browse)
 * - Recent activity
 */

import React, { useState, useEffect } from 'react';
import Link from 'next/link';

interface WikiStats {
  total_pages: number;
  by_category: { [key: string]: number };
  by_confidence: { [key: string]: number };
  last_ingest?: string;
  pages_this_week: number;
  health: {
    severity: 'low' | 'medium' | 'high';
    issues_count: number;
    stale_pages: number;
  };
}

interface WikiDashboardProps {
  wikiType: 'leading_practice' | 'project';
  projectId?: string;
}

export const WikiDashboard: React.FC<WikiDashboardProps> = ({
  wikiType,
  projectId,
}) => {
  const [stats, setStats] = useState<WikiStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const params = new URLSearchParams();
        if (projectId) params.append('project_id', projectId);

        const response = await fetch(
          `/api/wiki/${wikiType}/stats?${params.toString()}`
        );

        if (!response.ok) throw new Error('Failed to fetch stats');

        const data = await response.json();
        setStats(data.stats);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, [wikiType, projectId]);

  if (loading) {
    return <div className="p-8 text-center">Loading wiki dashboard...</div>;
  }

  if (error) {
    return <div className="p-8 text-red-600">Error: {error}</div>;
  }

  if (!stats) {
    return <div className="p-8">No wiki data available</div>;
  }

  const severityColor = {
    low: 'text-green-600',
    medium: 'text-yellow-600',
    high: 'text-red-600',
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">
          {wikiType === 'leading_practice' ? 'Leading Practices' : 'Project'} Wiki
        </h1>
        <p className="text-gray-600 mt-2">
          Knowledge base with auto-correction and health checks
        </p>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Link href={`/wiki/${wikiType}/search`} className="p-4 border rounded-lg hover:bg-gray-50 transition">
            <div className="font-semibold">Search</div>
            <div className="text-sm text-gray-600">Find pages and topics</div>
        </Link>

        <Link href={`/wiki/${wikiType}/browse`} className="p-4 border rounded-lg hover:bg-gray-50 transition">
            <div className="font-semibold">Browse</div>
            <div className="text-sm text-gray-600">View all pages</div>
        </Link>

        {wikiType === 'project' && (
          <Link href={`/wiki/${wikiType}/ingest`} className="p-4 border rounded-lg hover:bg-gray-50 transition bg-blue-50">
              <div className="font-semibold text-blue-600">+ Ingest</div>
              <div className="text-sm text-gray-600">Add sources</div>
          </Link>
        )}

        <Link href={`/wiki/${wikiType}/lint`} className="p-4 border rounded-lg hover:bg-gray-50 transition">
            <div className="font-semibold">Health Check</div>
            <div className="text-sm text-gray-600">Run lint</div>
        </Link>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Total Pages */}
        <div className="bg-white p-6 rounded-lg border">
          <div className="text-gray-600 text-sm font-medium">Total Pages</div>
          <div className="text-4xl font-bold mt-2">{stats.total_pages}</div>
          <div className="text-gray-600 text-sm mt-2">
            {stats.pages_this_week} this week
          </div>
        </div>

        {/* Health Status */}
        <div className="bg-white p-6 rounded-lg border">
          <div className="text-gray-600 text-sm font-medium">Health Status</div>
          <div className={`text-4xl font-bold mt-2 ${severityColor[stats.health.severity]}`}>
            {stats.health.severity.toUpperCase()}
          </div>
          <div className="text-gray-600 text-sm mt-2">
            {stats.health.issues_count} issue{stats.health.issues_count !== 1 ? 's' : ''}
          </div>
        </div>

        {/* Stale Pages */}
        <div className="bg-white p-6 rounded-lg border">
          <div className="text-gray-600 text-sm font-medium">Stale Pages</div>
          <div className="text-4xl font-bold mt-2">{stats.health.stale_pages}</div>
          <div className="text-gray-600 text-sm mt-2">
            Last ingest: {stats.last_ingest ? new Date(stats.last_ingest).toLocaleDateString() : 'Never'}
          </div>
        </div>
      </div>

      {/* Categories */}
      <div className="bg-white p-6 rounded-lg border">
        <h2 className="text-xl font-bold mb-4">Pages by Category</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Object.entries(stats.by_category).map(([category, count]) => (
            <Link key={category} href={`/wiki/${wikiType}/browse?category=${category}`} className="p-4 text-center border rounded hover:bg-gray-50 transition">
                <div className="font-semibold text-lg">{count}</div>
                <div className="text-sm text-gray-600 capitalize">{category}s</div>
            </Link>
          ))}
        </div>
      </div>

      {/* Confidence Breakdown */}
      <div className="bg-white p-6 rounded-lg border">
        <h2 className="text-xl font-bold mb-4">Content Confidence</h2>
        <div className="space-y-3">
          {Object.entries(stats.by_confidence).map(([level, count]) => (
            <div key={level} className="flex items-center justify-between">
              <span className="capitalize font-medium">{level}</span>
              <div className="flex items-center gap-2">
                <div className="w-32 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${
                      level === 'high'
                        ? 'bg-green-500'
                        : level === 'medium'
                        ? 'bg-yellow-500'
                        : 'bg-red-500'
                    }`}
                    style={{
                      width: `${(count / stats.total_pages) * 100}%`,
                    }}
                  />
                </div>
                <span className="text-sm text-gray-600 w-8">{count}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Health Alerts */}
      {stats.health.severity !== 'low' && (
        <div
          className={`p-4 rounded-lg ${
            stats.health.severity === 'high'
              ? 'bg-red-50 border border-red-200'
              : 'bg-yellow-50 border border-yellow-200'
          }`}
        >
          <h3 className="font-semibold mb-2">
            {stats.health.severity === 'high' ? '🔴' : '🟡'} Wiki Health Alert
          </h3>
          <p className="text-sm text-gray-700 mb-3">
            Your wiki has {stats.health.issues_count} issue{stats.health.issues_count !== 1 ? 's' : ''} that should be reviewed.
          </p>
          <Link href={`/wiki/${wikiType}/lint`} className="text-sm font-medium text-blue-600 hover:underline">
              View details and suggestions →
          </Link>
        </div>
      )}
    </div>
  );
};

export default WikiDashboard;
