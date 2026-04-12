"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";

interface WikiStats {
  total_pages: number;
  health: {
    severity: "low" | "medium" | "high";
    issues_count: number;
  };
  relationships?: {
    total_relationships: number;
    pages_with_links: number;
    connectivity: number;
  };
  communities?: {
    total_communities: number;
    avg_community_size: number;
  };
}

interface WikiPage {
  id: string;
  title: string;
  confidence?: string;
  updated_at?: string;
  importance_score?: number;
  inbound_links?: number;
  rank?: number;
}

export function WikiQuickAccess({ projectId }: { projectId: string }) {
  const { api } = useAuth();
  const [stats, setStats] = useState<WikiStats | null>(null);
  const [recentPages, setRecentPages] = useState<WikiPage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Fetch stats
        const statsRes = await api(
          `/api/wiki/project/stats?project_id=${encodeURIComponent(projectId)}`
        );
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          setStats(statsData.stats);
        }

        // Fetch god nodes (most important pages)
        const godNodesRes = await api(
          `/api/wiki/project/god-nodes?project_id=${encodeURIComponent(
            projectId
          )}&limit=5`
        );
        if (godNodesRes.ok) {
          const godNodesData = await godNodesRes.json();
          setRecentPages(godNodesData.god_nodes || []);
        }
      } catch (err) {
        console.error("Failed to fetch wiki quick access data:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [projectId, api]);

  const severityColor = {
    low: "text-green-600",
    medium: "text-yellow-600",
    high: "text-red-600",
  };

  const confidenceColor = {
    high: "bg-green-100 text-green-800",
    medium: "bg-yellow-100 text-yellow-800",
    low: "bg-red-100 text-red-800",
  };

  if (loading) {
    return (
      <div className="space-y-3 text-sm">
        <div className="text-gray-500">Loading wiki data...</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary Stats */}
      {stats && (
        <div className="rounded bg-gray-50 p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">
              📚 {stats.total_pages} pages
            </span>
            <span
              className={`text-xs font-medium ${
                severityColor[stats.health.severity]
              }`}
            >
              Health: {stats.health.severity === "low" ? "✓ Good" :
                        stats.health.severity === "medium" ? "⚠ Medium" :
                        "✗ Issues"}
            </span>
          </div>
          {stats.relationships && (
            <div className="text-xs text-gray-600">
              🔗 {stats.relationships.total_relationships} connections ({stats.relationships.connectivity}% linked)
            </div>
          )}
          {stats.communities && stats.communities.total_communities > 0 && (
            <div className="text-xs text-gray-600">
              🏘️ {stats.communities.total_communities} communities ({stats.communities.avg_community_size} pages avg)
            </div>
          )}
        </div>
      )}

      {/* God Nodes (Most Important Pages) */}
      {recentPages.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-gray-700 uppercase">
            ⭐ Most Important
          </p>
          <div className="space-y-2">
            {recentPages.slice(0, 5).map((page) => (
              <Link
                key={page.id}
                href={`/projects/${projectId}/wiki`}
                className="block rounded border border-gray-200 bg-white p-2 text-xs hover:bg-gray-50 transition"
              >
                <div className="flex items-start justify-between gap-1 mb-1">
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    {page.rank && (
                      <span className="flex-shrink-0 inline-block w-5 h-5 rounded-full bg-yellow-100 text-yellow-800 text-center leading-5 font-bold text-xs">
                        {page.rank}
                      </span>
                    )}
                    <span className="font-medium text-blue-600 truncate">
                      {page.title}
                    </span>
                  </div>
                </div>
                <div className="text-gray-500 text-xs">
                  {page.inbound_links !== undefined && (
                    <span>🔗 {page.inbound_links} refs</span>
                  )}
                  {page.importance_score !== undefined && (
                    <span className="ml-2">💪 {(page.importance_score * 100).toFixed(0)}%</span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {recentPages.length === 0 && stats && stats.total_pages > 0 && (
        <div className="text-xs text-gray-500">
          No recent pages loaded. Visit the full wiki to see all pages.
        </div>
      )}

      {stats && stats.total_pages === 0 && (
        <div className="text-xs text-gray-500">
          No wiki pages yet. Start by adding documents or writing pages.
        </div>
      )}

      {/* Link to Full Wiki */}
      <Link
        href={`/projects/${projectId}/wiki`}
        className="block w-full rounded bg-blue-100 px-3 py-2 text-center text-xs font-medium text-blue-700 hover:bg-blue-200 transition border border-blue-300"
      >
        📖 View Full Wiki →
      </Link>
    </div>
  );
}
