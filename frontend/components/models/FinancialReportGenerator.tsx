"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { Input } from "@/components/ui/Input";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

type ReportFormat = "xlsx";
type ReportType =
  | "variance"
  | "financial_statements"
  | "budget_vs_actual"
  | "forecast"
  | "comprehensive";

type ReportGeneratorState = {
  reportType: ReportType;
  format: ReportFormat;
  title: string;
  includeCharts: boolean;
  includeTables: boolean;
  recipients: string;
};

export function FinancialReportGenerator({
  onGenerate,
  isLoading = false,
}: {
  onGenerate: (config: ReportGeneratorState) => void;
  isLoading?: boolean;
}) {
  const [state, setState] = useState<ReportGeneratorState>({
    reportType: "comprehensive",
    format: "xlsx",
    title: "Financial Report",
    includeCharts: true,
    includeTables: true,
    recipients: "",
  });

  const [previewMode, setPreviewMode] = useState(false);

  const reportTypeDescriptions: Record<ReportType, string> = {
    variance: "Budget vs actual variance analysis",
    financial_statements: "Income statement, balance sheet, cash flow",
    budget_vs_actual: "Monthly budget vs actual tracking",
    forecast: "Financial projections and scenarios",
    comprehensive: "Complete financial analysis and statements",
  };

  const formatInfo: Record<ReportFormat, { label: string; description: string }> =
    {
      xlsx: {
        label: "Excel",
        description: "Multi-sheet workbook with formulas",
      },
    };

  const handleGenerate = async () => {
    onGenerate(state);
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[#0F0B0B]">
          Generate Financial Report
        </h2>
        <p className="mt-1 text-sm text-[#4C4C4C]">
          Create and export comprehensive financial reports
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Report Configuration */}
        <div className="lg:col-span-2 space-y-4">
          <Card className="bg-white">
            <div className="space-y-4 p-4">
              <div>
                <label htmlFor="frg-report-type" className="block text-sm font-medium text-[#0F0B0B]">
                  Report Type
                </label>
                <Select
                  id="frg-report-type"
                  value={state.reportType}
                  onChange={(e) =>
                    setState({ ...state, reportType: e.target.value as ReportType })
                  }
                  className="mt-1"
                >
                  {(
                    Object.entries(reportTypeDescriptions) as [
                      ReportType,
                      string
                    ][]
                  ).map(([type, desc]) => (
                    <option key={type} value={type}>
                      {type
                        .replace(/_/g, " ")
                        .replace(/^\w/, (c) => c.toUpperCase())}
                      - {desc}
                    </option>
                  ))}
                </Select>
              </div>

              <div>
                <label htmlFor="frg-title" className="block text-sm font-medium text-[#0F0B0B]">
                  Report Title
                </label>
                <Input
                  id="frg-title"
                  type="text"
                  value={state.title}
                  onChange={(e) => setState({ ...state, title: e.target.value })}
                  placeholder="e.g., Q4 2024 Financial Summary"
                  className="mt-1"
                />
              </div>

              <div>
                <span id="frg-export-format-label" className="block text-sm font-medium text-[#0F0B0B]">
                  Export Format
                </span>
                <div role="group" aria-labelledby="frg-export-format-label" className="mt-2 grid gap-2 sm:grid-cols-3">
                  {(Object.entries(formatInfo) as [ReportFormat, typeof formatInfo.xlsx][]).map(
                    ([format, info]) => (
                      <button
                        key={format}
                        onClick={() => setState({ ...state, format })}
                        className={`rounded-lg border-2 p-3 text-left transition ${
                          state.format === format
                            ? "border-[#86BC24] bg-[#f0f8f0]"
                            : "border-[#f0f0f0] hover:border-[#86BC24]"
                        }`}
                      >
                        <p className="font-semibold text-[#0F0B0B]">
                          {info.label}
                        </p>
                        <p className="text-xs text-[#4C4C4C]">
                          {info.description}
                        </p>
                      </button>
                    )
                  )}
                </div>
              </div>

              <div className="space-y-2 border-t border-[#f0f0f0] pt-4">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={state.includeCharts}
                    onChange={(e) =>
                      setState({ ...state, includeCharts: e.target.checked })
                    }
                    className="rounded"
                  />
                  <span className="text-sm text-[#0F0B0B]">
                    Include Charts & Visualizations
                  </span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={state.includeTables}
                    onChange={(e) =>
                      setState({ ...state, includeTables: e.target.checked })
                    }
                    className="rounded"
                  />
                  <span className="text-sm text-[#0F0B0B]">
                    Include Data Tables
                  </span>
                </label>
              </div>

              <div className="border-t border-[#f0f0f0] pt-4">
                <label htmlFor="frg-recipients" className="block text-sm font-medium text-[#0F0B0B]">
                  Email Recipients (Optional)
                </label>
                <Input
                  id="frg-recipients"
                  type="text"
                  value={state.recipients}
                  onChange={(e) =>
                    setState({ ...state, recipients: e.target.value })
                  }
                  placeholder="email@example.com, other@example.com"
                  className="mt-1"
                />
                <p className="mt-1 text-xs text-[#4C4C4C]">
                  Leave blank to download only
                </p>
              </div>
            </div>
          </Card>
        </div>

        {/* Preview & Actions */}
        <div className="space-y-3">
          <Card className="bg-[#f9f9f9]">
            <div className="space-y-4 p-4">
              <div>
                <p className="text-xs text-[#4C4C4C]">Report Summary</p>
                <div className="mt-2 space-y-2">
                  <div className="flex justify-between">
                    <span className="text-xs text-[#4C4C4C]">Type:</span>
                    <span className="text-xs font-semibold text-[#0F0B0B]">
                      {state.reportType.replace(/_/g, " ")}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-[#4C4C4C]">Format:</span>
                    <span className="text-xs font-semibold text-[#0F0B0B]">
                      {formatInfo[state.format].label}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-xs text-[#4C4C4C]">Components:</span>
                    <span className="text-xs font-semibold text-[#0F0B0B]">
                      {[
                        state.includeCharts && "Charts",
                        state.includeTables && "Tables",
                      ]
                        .filter(Boolean)
                        .join(", ")}
                    </span>
                  </div>
                </div>
              </div>

              <div className="space-y-2 border-t border-[#f0f0f0] pt-4">
                <Button
                  onClick={handleGenerate}
                  disabled={isLoading}
                  className="w-full"
                >
                  {isLoading ? "Generating..." : "Generate Report"}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setPreviewMode(!previewMode)}
                  className="w-full"
                >
                  {previewMode ? "Hide Preview" : "Preview"}
                </Button>
              </div>
            </div>
          </Card>

          {/* Report Templates */}
          <Card className="bg-white">
            <div className="space-y-3 p-4">
              <p className="text-xs font-semibold text-[#0F0B0B]">
                Quick Templates
              </p>
              {[
                { label: "Monthly Review", type: "variance", format: "xlsx" as const },
                {
                  label: "Board Presentation",
                  type: "comprehensive",
                  format: "xlsx" as const,
                },
                { label: "Data Export", type: "financial_statements", format: "xlsx" as const },
              ].map((template) => (
                <button
                  key={template.label}
                  onClick={() =>
                    setState({
                      ...state,
                      reportType: template.type as ReportType,
                      format: template.format,
                    })
                  }
                  className="block w-full rounded-lg bg-[#f9f9f9] px-3 py-2 text-left text-xs font-medium text-[#0F0B0B] transition hover:bg-[#f0f0f0]"
                >
                  {template.label}
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Preview Section */}
      {previewMode && (
        <Card className="bg-white">
          <div className="space-y-4 p-4">
            <h3 className="font-semibold text-[#0F0B0B]">Report Preview</h3>

            {/* Preview Header */}
            <div className="border-b border-[#f0f0f0] pb-4">
              <h4 className="text-lg font-bold text-[#0F0B0B]">
                {state.title}
              </h4>
              <p className="mt-1 text-xs text-[#4C4C4C]">
                Report Type: {state.reportType.replace(/_/g, " ")}
              </p>
            </div>

            {/* Sample Content */}
            <div className="space-y-4 text-xs text-[#4C4C4C]">
              {state.includeCharts && (
                <div>
                  <p className="mb-2 font-semibold text-[#0F0B0B]">
                    📊 Charts Section
                  </p>
                  <div className="rounded-lg bg-[#f9f9f9] px-3 py-8 text-center">
                    <p>[Financial charts will appear here]</p>
                  </div>
                </div>
              )}

              {state.includeTables && (
                <div>
                  <p className="mb-2 font-semibold text-[#0F0B0B]">
                    📋 Data Tables
                  </p>
                  <div className="rounded-lg bg-[#f9f9f9] p-3">
                    <p>[Financial tables will appear here]</p>
                  </div>
                </div>
              )}

              {state.recipients && (
                <div className="rounded-lg bg-[#fff8e6] px-3 py-2">
                  <p className="font-semibold text-[#8a6d00]">
                    Delivery will be attempted to: {state.recipients}
                  </p>
                  <p className="text-[#8a6d00]">
                    Requires email to be configured; you’ll get a confirmation after generating.
                  </p>
                </div>
              )}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
