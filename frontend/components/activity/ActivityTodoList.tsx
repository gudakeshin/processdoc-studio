"use client";

import React, { useMemo, useState } from "react";
import {
  Clock,
  CheckCircle2,
  AlertCircle,
  Loader2,
  XCircle,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import {
  useActivityTodos,
  formatTodoTimestamp,
  getTodoStatusColor,
  getTodoStatusLabel,
  type ActivityTodoItem,
} from "@/hooks/useActivityTodos";

interface ActivityTodoListProps {
  projectId: string;
  onTodoClick?: (runId: string) => void;
  maxItems?: number;
}

/**
 * Returns the appropriate icon for a todo status
 */
function getStatusIcon(
  status: "planned" | "executing" | "completed" | "failed" | "cancelled"
) {
  switch (status) {
    case "planned":
      return <Clock className="h-4 w-4 text-yellow-600" />;
    case "executing":
      return <Loader2 className="h-4 w-4 text-blue-600 animate-spin" />;
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-green-600" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-red-600" />;
    case "cancelled":
      return <AlertCircle className="h-4 w-4 text-gray-600" />;
    default:
      return <Clock className="h-4 w-4 text-gray-400" />;
  }
}

/**
 * Single activity todo item
 */
function ActivityTodoItem({
  item,
  onTodoClick,
}: {
  item: ActivityTodoItem;
  onTodoClick?: (runId: string) => void;
}) {
  return (
    <div
      onClick={() => onTodoClick?.(item.id)}
      className={`flex items-start gap-3 p-3 rounded-lg border transition-colors ${
        onTodoClick ? "cursor-pointer hover:bg-gray-50" : ""
      } bg-white border-gray-200`}
    >
      {/* Status Icon */}
      <div className="mt-0.5 flex-shrink-0">{getStatusIcon(item.status)}</div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        {/* Title */}
        <h4 className="text-sm font-medium text-gray-900 truncate" title={item.instruction}>
          {item.title}
        </h4>

        {/* Status & Time */}
        <div className="flex items-center gap-2 mt-1">
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getTodoStatusColor(
              item.status
            )}`}
          >
            {getTodoStatusLabel(item.status)}
          </span>
          <span className="text-xs text-gray-500">{formatTodoTimestamp(item.timestamp)}</span>
        </div>

        {/* Activity Count */}
        {item.eventCount > 0 && (
          <div className="text-xs text-gray-500 mt-1">{item.eventCount} activities</div>
        )}
      </div>
    </div>
  );
}

/**
 * Collapsible section for a category of todos
 */
function ActivityTodoSection({
  title,
  items,
  onTodoClick,
  defaultExpanded = true,
  emptyMessage = "No items",
}: {
  title: string;
  items: ActivityTodoItem[];
  onTodoClick?: (runId: string) => void;
  defaultExpanded?: boolean;
  emptyMessage?: string;
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  if (items.length === 0) {
    return (
      <div className="px-4 py-3">
        <p className="text-sm text-gray-500">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="border-b border-gray-200 last:border-b-0">
      {/* Section Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm text-gray-900">{title}</span>
          <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-gray-200 text-xs font-medium text-gray-700">
            {items.length}
          </span>
        </div>
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-gray-500" />
        ) : (
          <ChevronRight className="h-4 w-4 text-gray-500" />
        )}
      </button>

      {/* Section Items */}
      {isExpanded && (
        <div className="px-4 py-2 bg-gray-50 space-y-2">
          {items.map((item) => (
            <ActivityTodoItem key={item.id} item={item} onTodoClick={onTodoClick} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Main Activity To-Do List Component
 * Displays planned, executing, completed, and cancelled activities
 */
export function ActivityTodoList({
  projectId,
  onTodoClick,
  maxItems = 20,
}: ActivityTodoListProps) {
  const { planned, executing, completed, failed, cancelled, loading, error } = useActivityTodos(
    projectId,
    maxItems
  );

  const totalTodos = planned.length + executing.length + completed.length + failed.length;

  // Loading state
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-8">
        <Loader2 className="h-5 w-5 text-gray-400 animate-spin mb-2" />
        <p className="text-sm text-gray-500">Loading activities...</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
        <p className="text-sm text-red-700">Failed to load activities</p>
        <p className="text-xs text-red-600 mt-1">{error.message}</p>
      </div>
    );
  }

  // Empty state
  if (totalTodos === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8">
        <Clock className="h-8 w-8 text-gray-300 mb-2" />
        <p className="text-sm text-gray-500">No activities yet</p>
      </div>
    );
  }

  return (
    <div className="w-full bg-white rounded-lg border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
        <h3 className="text-sm font-semibold text-gray-900">Activity To-Do List</h3>
        <p className="text-xs text-gray-600 mt-1">{totalTodos} activities</p>
      </div>

      {/* Content */}
      <div>
        {/* Executing */}
        {executing.length > 0 && (
          <ActivityTodoSection
            title="Executing"
            items={executing}
            onTodoClick={onTodoClick}
            defaultExpanded={true}
            emptyMessage="No executing activities"
          />
        )}

        {/* Planned */}
        {planned.length > 0 && (
          <ActivityTodoSection
            title="Planned"
            items={planned}
            onTodoClick={onTodoClick}
            defaultExpanded={true}
            emptyMessage="No planned activities"
          />
        )}

        {/* Completed */}
        {completed.length > 0 && (
          <ActivityTodoSection
            title="Completed"
            items={completed}
            onTodoClick={onTodoClick}
            defaultExpanded={false}
            emptyMessage="No completed activities"
          />
        )}

        {/* Failed */}
        {failed.length > 0 && (
          <ActivityTodoSection
            title="Failed"
            items={failed}
            onTodoClick={onTodoClick}
            defaultExpanded={false}
            emptyMessage="No failed activities"
          />
        )}

        {/* Cancelled */}
        {cancelled.length > 0 && (
          <ActivityTodoSection
            title="Cancelled"
            items={cancelled}
            onTodoClick={onTodoClick}
            defaultExpanded={false}
            emptyMessage="No cancelled activities"
          />
        )}
      </div>
    </div>
  );
}
