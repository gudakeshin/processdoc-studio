"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { extractApiErrorMessage } from "@/lib/api-error";
import type { RunRow } from "@/types/api";

export interface ActivityTodoItem {
  id: string;
  title: string;
  status: "planned" | "executing" | "completed" | "failed" | "cancelled";
  timestamp: string | null;
  instruction: string;
  eventCount: number;
}

export interface ActivityTodosResult {
  planned: ActivityTodoItem[];
  executing: ActivityTodoItem[];
  completed: ActivityTodoItem[];
  failed: ActivityTodoItem[];
  cancelled: ActivityTodoItem[];
  all: ActivityTodoItem[];
  loading: boolean;
  error: Error | null;
}

/**
 * Maps backend run status to activity todo status
 */
function mapRunStatusToTodoStatus(
  runStatus: string
): "planned" | "executing" | "completed" | "failed" | "cancelled" {
  const status = (runStatus || "").toLowerCase().trim();

  // Planned statuses
  if (
    status === "planning" ||
    status === "pending" ||
    status === "pending_approval" ||
    status === "approved" ||
    status === "queued" ||
    status === "waiting"
  ) {
    return "planned";
  }

  // Executing statuses
  if (status === "running" || status === "in_progress") {
    return "executing";
  }

  // Completed statuses
  if (status === "completed" || status === "success" || status === "done") {
    return "completed";
  }

  // Failed statuses
  if (status === "failed" || status === "error") {
    return "failed";
  }

  // Cancelled statuses
  if (status === "cancelled" || status === "aborted" || status === "stopped") {
    return "cancelled";
  }

  // Default to planned if unknown
  return "planned";
}

/**
 * Converts a Run to an ActivityTodoItem
 */
function runToTodoItem(run: RunRow, eventCount: number = 0): ActivityTodoItem {
  return {
    id: run.id,
    title:
      run.instruction && run.instruction.length > 100
        ? run.instruction.substring(0, 97) + "..."
        : run.instruction || "[No instruction]",
    instruction: run.instruction || "",
    status: mapRunStatusToTodoStatus(run.status),
    timestamp: run.created_at,
    eventCount,
  };
}

/**
 * Hook to fetch runs and transform them into activity to-do items
 * Groups todos by status (planned, executing, completed, failed, cancelled)
 */
export function useActivityTodos(
  projectId: string,
  maxItems: number = 20,
  enabled: boolean = true
): ActivityTodosResult {
  const { api, token } = useAuth();
  const qc = useQueryClient();

  const { data: runs = [], isLoading, error } = useQuery({
    queryKey: ["activity-todos", projectId],
    enabled: enabled && Boolean(token && projectId),
    queryFn: async (): Promise<RunRow[]> => {
      const res = await api(`/api/runs?project_id=${encodeURIComponent(projectId)}`);
      const data = (await res.json().catch(() => ({}))) as { items?: RunRow[] };
      if (!res.ok) throw new Error(extractApiErrorMessage(data, "Failed to load activity todos"));
      return (data.items ?? []).slice(0, maxItems);
    },
    refetchInterval: 10000, // Refetch every 10 seconds for near-real-time updates
    refetchOnWindowFocus: true,
  });

  // Transform runs into todo items
  const allTodos = runs.map((run) => runToTodoItem(run, 0));

  // Group by status
  const grouped = {
    planned: allTodos.filter((t) => t.status === "planned"),
    executing: allTodos.filter((t) => t.status === "executing"),
    completed: allTodos.filter((t) => t.status === "completed"),
    failed: allTodos.filter((t) => t.status === "failed"),
    cancelled: allTodos.filter((t) => t.status === "cancelled"),
  };

  return {
    ...grouped,
    all: allTodos,
    loading: isLoading,
    error: error instanceof Error ? error : null,
  };
}

/**
 * Helper to format a todo item's timestamp as relative time
 * Example: "2 hours ago", "just now", "3 days ago"
 */
export function formatTodoTimestamp(timestamp: string | null): string {
  if (!timestamp) return "unknown";

  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  // Fallback to date format
  return date.toLocaleDateString();
}

/**
 * Get status badge color for UI rendering
 */
export function getTodoStatusColor(
  status: "planned" | "executing" | "completed" | "failed" | "cancelled"
): string {
  switch (status) {
    case "planned":
      return "bg-yellow-100 text-yellow-800";
    case "executing":
      return "bg-blue-100 text-blue-800";
    case "completed":
      return "bg-green-100 text-green-800";
    case "failed":
      return "bg-red-100 text-red-800";
    case "cancelled":
      return "bg-gray-100 text-gray-800";
    default:
      return "bg-gray-100 text-gray-800";
  }
}

/**
 * Get status badge label for UI rendering
 */
export function getTodoStatusLabel(
  status: "planned" | "executing" | "completed" | "failed" | "cancelled"
): string {
  switch (status) {
    case "planned":
      return "Planned";
    case "executing":
      return "Executing";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Unknown";
  }
}
