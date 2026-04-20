"use client";

import { useState, useMemo } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";

type ConflictType = "formula_changed" | "type_mismatch" | "structural_shift" | "value_mismatch";
type ConflictStatus = "open" | "resolved" | "reopened";
type ConflictSeverity = "high" | "medium" | "low";

type CellVersion = {
  timestamp: string;
  value: unknown;
  source: "base" | "local" | "remote";
  user?: string;
};

type ConflictImpact = {
  dependentCells: string[];
  affectedModels: string[];
  impactCount: number;
};

type ModelConflict = {
  id: string;
  sheet: string;
  cell_ref: string;
  type: ConflictType;
  severity: ConflictSeverity;
  status: ConflictStatus;
  base?: { value: unknown };
  local?: { value: unknown };
  remote?: { value: unknown };
  history?: CellVersion[];
  impact?: ConflictImpact;
  formula?: string;
  createdAt: string;
  resolvedAt?: string;
};

type ResolutionMode = "single" | "batch" | "history" | "impact";

export function EnhancedConflictResolution({
  conflicts: initialConflicts = [],
  onResolve,
  onBatchResolve,
}: {
  conflicts?: ModelConflict[];
  onResolve?: (conflictId: string, chosenSide: string) => void;
  onBatchResolve?: (strategy: string) => void;
}) {
  const [mode, setMode] = useState<ResolutionMode>("single");
  const [selectedConflictId, setSelectedConflictId] = useState<string>("");
  const [filters, setFilters] = useState({
    sheet: "",
    severity: "",
    status: "",
  });
  const [batchStrategy, setBatchStrategy] = useState<"assumptions" | "computed" | "all">("all");
  const [message, setMessage] = useState("");

  const filteredConflicts = useMemo(() => {
    return initialConflicts.filter((c) => {
      if (filters.sheet && c.sheet !== filters.sheet) return false;
      if (filters.severity && c.severity !== filters.severity) return false;
      if (filters.status && c.status !== filters.status) return false;
      return true;
    });
  }, [initialConflicts, filters]);

  const selectedConflict = useMemo(
    () => filteredConflicts.find((c) => c.id === selectedConflictId),
    [filteredConflicts, selectedConflictId]
  );

  const sheets = useMemo(
    () => Array.from(new Set(initialConflicts.map((x) => x.sheet))).sort(),
    [initialConflicts]
  );

  const unresolvedCount = filteredConflicts.filter((c) => c.status === "open").length;

  const handleSingleResolve = (conflictId: string, side: string) => {
    onResolve?.(conflictId, side);
    setMessage(`✓ Resolved ${conflictId} with ${side}`);
    setTimeout(() => setMessage(""), 3000);
  };

  const handleBatchResolve = () => {
    onBatchResolve?.(batchStrategy);
    setMessage(`✓ Batch resolved ${unresolvedCount} conflicts using ${batchStrategy} strategy`);
    setTimeout(() => setMessage(""), 3000);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-[#0F0B0B]">
          Conflict Resolution Center
        </h2>
        <p className="mt-1 text-sm text-[#4C4C4C]">
          Resolve cell-level conflicts before synchronization
        </p>
      </div>

      {/* Mode Selector */}
      <div className="flex gap-2 border-b border-[#f0f0f0]">
        {(["single", "batch", "history", "impact"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-4 py-2 text-sm font-medium transition ${
              mode === m
                ? "border-b-2 border-[#86BC24] text-[#86BC24]"
                : "text-[#4C4C4C] hover:text-[#0F0B0B]"
            }`}
          >
            {m === "single" && "Single Resolution"}
            {m === "batch" && "Batch Resolution"}
            {m === "history" && "Cell History"}
            {m === "impact" && "Impact Analysis"}
          </button>
        ))}
      </div>

      {/* Filter Controls */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Select
          value={filters.sheet}
          onChange={(e) => setFilters({ ...filters, sheet: e.target.value })}
        >
          <option value="">All sheets</option>
          {sheets.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>

        <Select
          value={filters.severity}
          onChange={(e) => setFilters({ ...filters, severity: e.target.value })}
        >
          <option value="">All severities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </Select>

        <Select
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="reopened">Reopened</option>
        </Select>
      </div>

      {/* Status Cards */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="bg-white">
          <div className="p-4">
            <p className="text-xs text-[#4C4C4C]">Total Conflicts</p>
            <p className="mt-2 text-2xl font-bold text-[#0F0B0B]">
              {filteredConflicts.length}
            </p>
          </div>
        </Card>
        <Card className="bg-white border-l-4 border-orange-500">
          <div className="p-4">
            <p className="text-xs text-[#4C4C4C]">Unresolved</p>
            <p className="mt-2 text-2xl font-bold text-orange-600">
              {unresolvedCount}
            </p>
          </div>
        </Card>
        <Card className="bg-white border-l-4 border-[#86BC24]">
          <div className="p-4">
            <p className="text-xs text-[#4C4C4C]">Resolved</p>
            <p className="mt-2 text-2xl font-bold text-[#86BC24]">
              {filteredConflicts.filter((c) => c.status === "resolved").length}
            </p>
          </div>
        </Card>
      </div>

      {/* Single Resolution Mode */}
      {mode === "single" && (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            {/* Conflict List */}
            <div className="space-y-2 max-h-96 overflow-auto">
              <p className="text-sm font-semibold text-[#0F0B0B]">Conflicts</p>
              {filteredConflicts.length === 0 ? (
                <p className="text-xs text-[#4C4C4C]">No conflicts found</p>
              ) : (
                filteredConflicts.map((conflict) => (
                  <button
                    key={conflict.id}
                    onClick={() => setSelectedConflictId(conflict.id)}
                    className={`w-full rounded-lg border p-3 text-left transition ${
                      selectedConflictId === conflict.id
                        ? "border-[#86BC24] bg-[#f0f8f0]"
                        : "border-[#f0f0f0] hover:border-[#86BC24]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="font-mono text-sm font-semibold text-[#0F0B0B]">
                          {conflict.cell_ref}
                        </p>
                        <p className="text-xs text-[#4C4C4C]">
                          {conflict.sheet} • {conflict.type}
                        </p>
                      </div>
                      <Badge
                        variant={
                          conflict.severity === "high"
                            ? "error"
                            : conflict.severity === "medium"
                            ? "warning"
                            : "info"
                        }
                      >
                        {conflict.severity}
                      </Badge>
                    </div>
                  </button>
                ))
              )}
            </div>

            {/* Conflict Details */}
            {selectedConflict && (
              <Card className="bg-[#f9f9f9] sticky top-0">
                <div className="space-y-4 p-4">
                  <div>
                    <p className="text-xs font-semibold text-[#4C4C4C]">Cell Reference</p>
                    <p className="mt-1 font-mono text-lg font-bold text-[#0F0B0B]">
                      {selectedConflict.cell_ref}
                    </p>
                  </div>

                  {selectedConflict.formula && (
                    <div className="rounded-lg bg-white p-2">
                      <p className="text-xs font-semibold text-[#4C4C4C]">Formula</p>
                      <p className="mt-1 font-mono text-xs text-[#0F0B0B]">
                        {selectedConflict.formula}
                      </p>
                    </div>
                  )}

                  <div className="grid gap-2 grid-cols-3">
                    {[
                      { label: "Base", value: selectedConflict.base?.value },
                      { label: "Local", value: selectedConflict.local?.value },
                      { label: "Remote", value: selectedConflict.remote?.value },
                    ].map((item) => (
                      <div key={item.label} className="rounded-lg bg-white p-2">
                        <p className="text-xs font-semibold text-[#4C4C4C]">
                          {item.label}
                        </p>
                        <p className="mt-1 font-mono text-xs text-[#0F0B0B]">
                          {JSON.stringify(item.value)}
                        </p>
                      </div>
                    ))}
                  </div>

                  <div className="space-y-2 border-t border-[#e0e0e0] pt-3">
                    <Button
                      onClick={() => handleSingleResolve(selectedConflict.id, "local")}
                      className="w-full"
                    >
                      Keep Local
                    </Button>
                    <Button
                      onClick={() => handleSingleResolve(selectedConflict.id, "remote")}
                      className="w-full"
                    >
                      Keep Remote
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => handleSingleResolve(selectedConflict.id, "policy")}
                      className="w-full"
                    >
                      Resolve by Policy
                    </Button>
                  </div>
                </div>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* Batch Resolution Mode */}
      {mode === "batch" && (
        <Card className="bg-[#f0f8f0] border-l-4 border-[#86BC24]">
          <div className="space-y-4 p-4">
            <div>
              <h3 className="font-semibold text-[#0F0B0B]">
                Batch Resolve {unresolvedCount} Conflicts
              </h3>
              <p className="mt-1 text-sm text-[#4C4C4C]">
                Apply a resolution strategy to all unresolved conflicts
              </p>
            </div>

            <div className="space-y-2">
              {[
                {
                  id: "assumptions",
                  label: "Assumptions First",
                  desc: "Assumption cells use last-write-wins, computed cells use ProcessDoc",
                },
                {
                  id: "computed",
                  label: "Computed First",
                  desc: "All computed cells use ProcessDoc version, others last-write-wins",
                },
                {
                  id: "all",
                  label: "Full Policy",
                  desc: "Apply complete conflict policy across all cell types",
                },
              ].map((strategy) => (
                <label
                  key={strategy.id}
                  className={`rounded-lg border-2 p-3 cursor-pointer transition ${
                    batchStrategy === strategy.id
                      ? "border-[#86BC24] bg-white"
                      : "border-[#f0f0f0] hover:border-[#86BC24]"
                  }`}
                >
                  <input
                    type="radio"
                    name="strategy"
                    value={strategy.id}
                    checked={batchStrategy === strategy.id}
                    onChange={(e) => setBatchStrategy(e.target.value as any)}
                    className="mr-2"
                  />
                  <span className="font-semibold text-[#0F0B0B]">
                    {strategy.label}
                  </span>
                  <p className="mt-1 text-xs text-[#4C4C4C]">{strategy.desc}</p>
                </label>
              ))}
            </div>

            <Button
              onClick={handleBatchResolve}
              className="w-full"
            >
              Apply {batchStrategy} Strategy
            </Button>
          </div>
        </Card>
      )}

      {/* Cell History Mode */}
      {mode === "history" && selectedConflict?.history && (
        <Card className="bg-white">
          <div className="space-y-3 p-4">
            <h3 className="font-semibold text-[#0F0B0B]">
              Cell History: {selectedConflict.cell_ref}
            </h3>
            <div className="space-y-2">
              {selectedConflict.history.map((version, idx) => (
                <div
                  key={idx}
                  className="rounded-lg border border-[#f0f0f0] p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                      <p className="text-xs text-[#4C4C4C]">
                        {new Date(version.timestamp).toLocaleString()}
                      </p>
                      <p className="mt-1 font-mono font-semibold text-[#0F0B0B]">
                        {JSON.stringify(version.value)}
                      </p>
                      {version.user && (
                        <p className="mt-1 text-xs text-[#4C4C4C]">
                          By {version.user}
                        </p>
                      )}
                    </div>
                    <Badge variant="info">{version.source}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Impact Analysis Mode */}
      {mode === "impact" && selectedConflict?.impact && (
        <Card className="bg-white">
          <div className="space-y-4 p-4">
            <h3 className="font-semibold text-[#0F0B0B]">
              Impact Analysis: {selectedConflict.cell_ref}
            </h3>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-[#f9f9f9] p-3">
                <p className="text-xs font-semibold text-[#4C4C4C]">
                  Dependent Cells ({selectedConflict.impact.dependentCells.length})
                </p>
                <div className="mt-2 space-y-1">
                  {selectedConflict.impact.dependentCells.map((cell) => (
                    <p
                      key={cell}
                      className="font-mono text-xs text-[#0F0B0B]"
                    >
                      {cell}
                    </p>
                  ))}
                </div>
              </div>

              <div className="rounded-lg bg-[#f9f9f9] p-3">
                <p className="text-xs font-semibold text-[#4C4C4C]">
                  Affected Models ({selectedConflict.impact.affectedModels.length})
                </p>
                <div className="mt-2 space-y-1">
                  {selectedConflict.impact.affectedModels.map((model) => (
                    <p
                      key={model}
                      className="font-mono text-xs text-[#0F0B0B]"
                    >
                      {model}
                    </p>
                  ))}
                </div>
              </div>
            </div>

            <div className="rounded-lg bg-orange-50 border border-orange-200 p-3">
              <p className="text-sm font-semibold text-orange-900">
                ⚠️ Total Impact: {selectedConflict.impact.impactCount} cells/models affected
              </p>
              <p className="mt-1 text-xs text-orange-700">
                Resolving this conflict will cascade changes to dependent cells
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Status Message */}
      {message && (
        <div className="rounded-lg bg-[#f0f8f0] border border-[#86BC24] p-3 text-sm text-[#86BC24]">
          {message}
        </div>
      )}
    </div>
  );
}
