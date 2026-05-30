"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";

type EventType =
  | "model_created"
  | "model_updated"
  | "conflict_detected"
  | "conflict_resolved"
  | "assumption_changed"
  | "sync_completed"
  | "external_data_synced"
  | "budget_recorded";

export type AuditEvent = {
  id: string;
  timestamp: string;
  eventType: EventType;
  user?: string;
  modelId: string;
  cellRef?: string;
  oldValue?: unknown;
  newValue?: unknown;
  metadata?: Record<string, unknown>;
  severity: "info" | "warning" | "critical";
};

type ExportFormat = "csv" | "json" | "pdf";

const eventTypeDescriptions: Record<EventType, string> = {
  model_created: "Model Created",
  model_updated: "Model Updated",
  conflict_detected: "Conflict Detected",
  conflict_resolved: "Conflict Resolved",
  assumption_changed: "Assumption Changed",
  sync_completed: "Sync Completed",
  external_data_synced: "External Data Synced",
  budget_recorded: "Budget Recorded",
};

export function AuditLogViewer({
  events = [],
  total,
  hasMore,
  onLoadMore,
  onFilterChange,
  onExport,
}: {
  events?: AuditEvent[];
  total?: number;
  hasMore?: boolean;
  onLoadMore?: () => void;
  onFilterChange?: (filters: { event_type?: string; cell_ref?: string }) => void;
  onExport?: (events: AuditEvent[], format: ExportFormat) => void;
}) {
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [cellRefFilter, setCellRefFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [dateRange, setDateRange] = useState({ from: "", to: "" });
  const [expandedId, setExpandedId] = useState<string>("");
  const [exportFormat, setExportFormat] = useState<ExportFormat>("csv");

  function applyFilter(event_type: string, cell_ref: string) {
    onFilterChange?.({ event_type: event_type || undefined, cell_ref: cell_ref || undefined });
  }

  const filteredEvents = events.filter((event) => {
    if (severityFilter && event.severity !== severityFilter) return false;
    if (dateRange.from && new Date(event.timestamp) < new Date(dateRange.from)) return false;
    if (dateRange.to && new Date(event.timestamp) > new Date(dateRange.to)) return false;
    return true;
  });

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "critical": return "error";
      case "warning": return "warning";
      default: return "info";
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[#0F0B0B]">Audit Log</h2>
        <p className="mt-1 text-sm text-[#4C4C4C]">
          Complete compliance trail of all model changes and operations
        </p>
      </div>

      {/* Filter Controls */}
      <Card className="bg-white">
        <div className="space-y-4 p-4">
          <p className="text-sm font-semibold text-[#0F0B0B]">Filters</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Select
              value={eventTypeFilter}
              onChange={(e) => {
                setEventTypeFilter(e.target.value);
                applyFilter(e.target.value, cellRefFilter);
              }}
            >
              <option value="">All Event Types</option>
              {Object.entries(eventTypeDescriptions).map(([type, label]) => (
                <option key={type} value={type}>{label}</option>
              ))}
            </Select>

            <Input
              type="text"
              placeholder="Filter by cell ref (e.g. B4)..."
              value={cellRefFilter}
              onChange={(e) => {
                setCellRefFilter(e.target.value);
                applyFilter(eventTypeFilter, e.target.value);
              }}
            />

            <Select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
            >
              <option value="">All Severities</option>
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </Select>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="audit-from-date" className="block text-xs font-medium text-[#4C4C4C]">
                From Date
              </label>
              <Input
                id="audit-from-date"
                type="datetime-local"
                value={dateRange.from}
                onChange={(e) => setDateRange({ ...dateRange, from: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <label htmlFor="audit-to-date" className="block text-xs font-medium text-[#4C4C4C]">
                To Date
              </label>
              <Input
                id="audit-to-date"
                type="datetime-local"
                value={dateRange.to}
                onChange={(e) => setDateRange({ ...dateRange, to: e.target.value })}
                className="mt-1"
              />
            </div>
          </div>
        </div>
      </Card>

      {/* Export Controls */}
      <Card className="bg-[#f0f8f0] border-l-4 border-[#86BC24]">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold text-[#0F0B0B]">
              {filteredEvents.length} Events Shown
            </p>
            {total !== undefined && (
              <p className="text-xs text-[#4C4C4C]">Total matching: {total}</p>
            )}
          </div>
          <div className="flex gap-2">
            <Select
              value={exportFormat}
              onChange={(e) => setExportFormat(e.target.value as ExportFormat)}
            >
              <option value="csv">CSV</option>
              <option value="json">JSON</option>
              <option value="pdf">PDF</option>
            </Select>
            <button
              onClick={() => onExport?.(filteredEvents, exportFormat)}
              className="rounded-lg bg-[#86BC24] px-4 py-2 text-sm font-medium text-white hover:bg-[#7aa71f] transition"
            >
              Export
            </button>
          </div>
        </div>
      </Card>

      {/* Event Timeline */}
      <div className="space-y-2">
        {filteredEvents.length === 0 ? (
          <Card className="bg-white">
            <div className="p-8 text-center">
              <p className="text-sm text-[#4C4C4C]">No events match your filters</p>
            </div>
          </Card>
        ) : (
          filteredEvents.map((event) => (
            <Card key={event.id} className="bg-white">
              <button
                onClick={() => setExpandedId(expandedId === event.id ? "" : event.id)}
                className="w-full p-4 text-left transition hover:bg-[#f9f9f9]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-semibold text-[#0F0B0B]">
                        {eventTypeDescriptions[event.eventType] ?? event.eventType}
                      </p>
                      <Badge variant={getSeverityColor(event.severity)}>
                        {event.severity}
                      </Badge>
                    </div>
                    <div className="mt-1 flex items-center gap-4 text-xs text-[#4C4C4C]">
                      <span>{new Date(event.timestamp).toLocaleString()}</span>
                      {event.user && <span>User: {event.user}</span>}
                      {event.cellRef && <span>Cell: {event.cellRef}</span>}
                    </div>
                  </div>
                  <div className="text-[#86BC24]">
                    {expandedId === event.id ? "▼" : "▶"}
                  </div>
                </div>

                {expandedId === event.id && (
                  <div className="mt-4 space-y-3 border-t border-[#f0f0f0] pt-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-lg bg-[#f9f9f9] p-3">
                        <p className="text-xs font-semibold text-[#4C4C4C]">Model ID</p>
                        <p className="mt-1 font-mono text-sm text-[#0F0B0B]">{event.modelId}</p>
                      </div>
                      <div className="rounded-lg bg-[#f9f9f9] p-3">
                        <p className="text-xs font-semibold text-[#4C4C4C]">Event Type</p>
                        <p className="mt-1 font-mono text-sm text-[#0F0B0B]">{event.eventType}</p>
                      </div>
                    </div>

                    {event.oldValue !== undefined && (
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-lg bg-red-50 border border-red-200 p-3">
                          <p className="text-xs font-semibold text-red-700">Previous Value</p>
                          <p className="mt-1 font-mono text-sm text-red-900">{JSON.stringify(event.oldValue)}</p>
                        </div>
                        <div className="rounded-lg bg-green-50 border border-green-200 p-3">
                          <p className="text-xs font-semibold text-green-700">New Value</p>
                          <p className="mt-1 font-mono text-sm text-green-900">{JSON.stringify(event.newValue)}</p>
                        </div>
                      </div>
                    )}

                    {event.metadata && Object.keys(event.metadata).length > 0 && (
                      <div className="rounded-lg bg-[#f9f9f9] p-3">
                        <p className="text-xs font-semibold text-[#4C4C4C]">Additional Metadata</p>
                        <pre className="mt-2 overflow-auto rounded bg-white p-2 text-xs font-mono text-[#0F0B0B]">
                          {JSON.stringify(event.metadata, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </button>
            </Card>
          ))
        )}
      </div>

      {/* Load more */}
      {hasMore && onLoadMore && (
        <div className="flex justify-center pt-2">
          <button
            onClick={onLoadMore}
            className="rounded-lg border border-[#86BC24] px-6 py-2 text-sm font-medium text-[#86BC24] hover:bg-[#f0f8f0] transition"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
