"use client";

import { useAuth } from "@/lib/auth-context";
import React, { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";

interface GraphNode {
  id: string;
  title: string;
}

interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  confidence: string;
}

interface WikiGraphProps {
  wikiType: "leading_practice" | "project";
  projectId?: string;
}

export const WikiGraph: React.FC<WikiGraphProps> = ({ wikiType, projectId }) => {
  const { api } = useAuth();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const run = async () => {
      try {
        setLoading(true);
        setError(null);
        const params = new URLSearchParams();
        if (projectId) params.append("project_id", projectId);
        params.append("limit_nodes", "80");
        const res = await api(`/api/wiki/${wikiType}/graph/data?${params}`);
        if (!res.ok) throw new Error(`Failed to load graph (${res.status})`);
        const data = await res.json();
        setNodes(data.nodes ?? []);
        setEdges(data.edges ?? []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };
    void run();
  }, [api, wikiType, projectId]);

  const layout = useMemo(() => {
    const width = 880;
    const height = 560;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) * 0.38;
    const positions = new Map<string, { x: number; y: number }>();
    const total = Math.max(nodes.length, 1);
    nodes.forEach((n, i) => {
      const theta = (2 * Math.PI * i) / total;
      positions.set(n.id, { x: cx + radius * Math.cos(theta), y: cy + radius * Math.sin(theta) });
    });
    return { width, height, positions };
  }, [nodes]);

  if (loading) return <p className="text-xs text-[var(--text-muted)]">Rendering graph…</p>;
  if (error) return <p className="text-xs text-[var(--error)]">{error}</p>;
  if (nodes.length === 0) {
    return <EmptyState title="No graph yet" description="No nodes found. Ingest content and create wiki-links first." />;
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-[var(--text-muted)]">
        Rendered graph: {nodes.length} nodes, {edges.length} edges
      </div>
      <div className="border border-[var(--surface-border)] bg-white overflow-auto">
        <svg viewBox={`0 0 ${layout.width} ${layout.height}`} className="w-full h-[560px]">
          {edges.map((e, i) => {
            const s = layout.positions.get(e.source);
            const t = layout.positions.get(e.target);
            if (!s || !t) return null;
            return (
              <line
                key={`${e.source}-${e.target}-${i}`}
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke="currentColor"
                strokeOpacity={0.25}
                strokeWidth={Math.max(1, Math.min(3, e.weight * 2))}
                className="text-gray-500"
              />
            );
          })}
          {nodes.map((n) => {
            const p = layout.positions.get(n.id);
            if (!p) return null;
            return (
              <g key={n.id}>
                <circle cx={p.x} cy={p.y} r={8} className="fill-blue-500" />
                <text x={p.x + 10} y={p.y + 4} className="fill-gray-700 text-[10px]">
                  {n.title.length > 28 ? `${n.title.slice(0, 26)}…` : n.title}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
};

export default WikiGraph;
