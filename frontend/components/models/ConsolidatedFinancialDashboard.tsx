"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Select } from "@/components/ui/Select";
import type {
  ConsolidatedFinancialMetrics,
  ConsolidatedFinancialStatement,
  ConsolidatedVarianceData,
  ConsolidatedForecastData,
} from "@/hooks/useModels";

type DashboardTab = "overview" | "statements" | "variance" | "forecast" | "assumptions";

const DashboardChart = dynamic(() => import("@/components/models/ModelDashboardChart"), {
  ssr: false,
  loading: () => <p className="text-xs text-[#4C4C4C]">Loading...</p>,
});

function numericRows(values?: number[]) {
  return Array.isArray(values) ? values : [];
}

function fmtRatio(v: number | null | undefined, decimals = 2): string {
  return v == null ? "N/A" : v.toFixed(decimals);
}

function fmtPct(v: number | null | undefined): string {
  return v == null ? "N/A" : `${(v * 100).toFixed(1)}%`;
}

function fmtX(v: number | null | undefined): string {
  return v == null ? "N/A" : `${v.toFixed(1)}x`;
}

export function ConsolidatedFinancialDashboard({
  metrics,
  statements,
  variances,
  forecasts,
  assumptions,
  dataSource,
}: {
  metrics?: ConsolidatedFinancialMetrics;
  statements?: ConsolidatedFinancialStatement;
  variances?: ConsolidatedVarianceData[];
  forecasts?: ConsolidatedForecastData[];
  assumptions?: Record<string, number>;
  dataSource?: "snapshot" | "assumptions";
}) {
  const [activeTab, setActiveTab] = useState<DashboardTab>("overview");
  const [selectedScenario, setSelectedScenario] = useState("base");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#0F0B0B]">
            Financial Dashboard
          </h1>
          <p className="mt-1 text-sm text-[#4C4C4C]">
            Comprehensive view of financial performance and projections
          </p>
          {dataSource && (
            <span className={`mt-1 inline-block rounded px-2 py-0.5 text-xs font-medium ${
              dataSource === "snapshot"
                ? "bg-green-100 text-green-800"
                : "bg-yellow-100 text-yellow-800"
            }`}>
              Data source: {dataSource === "snapshot" ? "Excel upload" : "Assumptions only — upload a workbook for balance sheet metrics"}
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <Select
            value={selectedScenario}
            onChange={(e) => setSelectedScenario(e.target.value)}
          >
            <option value="base">Base Case</option>
            <option value="upside">Upside</option>
            <option value="downside">Downside</option>
          </Select>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-[#f0f0f0]">
        {(["overview", "statements", "variance", "forecast", "assumptions"] as const).map(
          (tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium transition ${
                activeTab === tab
                  ? "border-b-2 border-[#86BC24] text-[#86BC24]"
                  : "text-[#4C4C4C] hover:text-[#0F0B0B]"
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          )
        )}
      </div>

      {/* Tab Content */}
      <div>
        {/* Overview Tab */}
        {activeTab === "overview" && metrics && (
          <div className="space-y-6">
            {/* Profitability Metrics */}
            <div>
              <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                Profitability
              </h3>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                {[
                  { label: "Gross Margin", display: fmtPct(metrics.profitability.grossMargin) },
                  { label: "Operating Margin", display: fmtPct(metrics.profitability.operatingMargin) },
                  { label: "Net Margin", display: fmtPct(metrics.profitability.netMargin) },
                  { label: "ROE", display: fmtPct(metrics.profitability.roe) },
                  { label: "ROIC", display: fmtPct(metrics.profitability.roic) },
                ].map((metric) => (
                  <Card key={metric.label} className="bg-white">
                    <div className="p-4">
                      <p className="text-xs text-[#4C4C4C]">{metric.label}</p>
                      <p className={`mt-2 text-lg font-bold ${metric.display === "N/A" ? "text-[#9CA3AF]" : "text-[#86BC24]"}`}>
                        {metric.display}
                      </p>
                    </div>
                  </Card>
                ))}
              </div>
            </div>

            {/* Liquidity Metrics */}
            <div>
              <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                Liquidity
              </h3>
              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { label: "Current Ratio", display: metrics.liquidity.currentRatio == null ? "N/A" : `${fmtRatio(metrics.liquidity.currentRatio)}x` },
                  { label: "Quick Ratio", display: metrics.liquidity.quickRatio == null ? "N/A" : `${fmtRatio(metrics.liquidity.quickRatio)}x` },
                  { label: "Cash Conversion Cycle", display: metrics.liquidity.cashConversionCycle == null ? "N/A" : `${Math.round(metrics.liquidity.cashConversionCycle)} days` },
                ].map((metric) => (
                  <Card key={metric.label} className="bg-white">
                    <div className="p-4">
                      <p className="text-xs text-[#4C4C4C]">{metric.label}</p>
                      <p className={`mt-2 text-lg font-bold ${metric.display === "N/A" ? "text-[#9CA3AF]" : "text-[#0F0B0B]"}`}>
                        {metric.display}
                      </p>
                    </div>
                  </Card>
                ))}
              </div>
            </div>

            {/* Leverage Metrics */}
            <div>
              <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                Leverage
              </h3>
              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { label: "Debt/Equity", display: fmtRatio(metrics.leverage.debtToEquity) },
                  { label: "Interest Coverage", display: fmtX(metrics.leverage.interestCoverage) },
                  { label: "Net Debt/EBITDA", display: fmtX(metrics.leverage.netDebtToEbitda) },
                ].map((metric) => (
                  <Card key={metric.label} className="bg-white">
                    <div className="p-4">
                      <p className="text-xs text-[#4C4C4C]">{metric.label}</p>
                      <p className={`mt-2 text-lg font-bold ${metric.display === "N/A" ? "text-[#9CA3AF]" : "text-[#0F0B0B]"}`}>
                        {metric.display}
                      </p>
                    </div>
                  </Card>
                ))}
              </div>
            </div>

            {/* Growth Metrics */}
            <div>
              <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                Growth
              </h3>
              <div className="grid gap-3 sm:grid-cols-4">
                {[
                  { label: "Revenue Growth", value: metrics.growth.revenueGrowth, format: "pct" },
                  { label: "EBITDA Growth", value: metrics.growth.ebitdaGrowth, format: "pct" },
                  { label: "FCF Growth", value: metrics.growth.fcfGrowth, format: "pct" },
                  { label: "CAGR", value: metrics.growth.cagr, format: "pct" },
                ].map((metric) => (
                  <Card key={metric.label} className="bg-white">
                    <div className="p-4">
                      <p className="text-xs text-[#4C4C4C]">{metric.label}</p>
                      <p className="mt-2 text-lg font-bold text-[#86BC24]">
                        {metric.format === "pct"
                          ? `${(metric.value * 100).toFixed(1)}%`
                          : metric.value.toFixed(2)}
                      </p>
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Statements Tab */}
        {activeTab === "statements" && statements && (
          <div className="space-y-6">
            <Card className="bg-white">
              <div className="p-4">
                <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                  Income Statement - {statements.name}
                </h3>
                <div className="overflow-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#f0f0f0]">
                        <th className="px-3 py-2 text-left font-semibold text-[#0F0B0B]">
                          Period
                        </th>
                        {(statements.periods ?? []).map((period) => (
                          <th
                            key={period}
                            className="px-3 py-2 text-right font-semibold text-[#0F0B0B]"
                          >
                            {period}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#f0f0f0]">
                      {[
                        { label: "Revenue", values: numericRows(statements.revenue) },
                        { label: "COGS", values: numericRows(statements.cogs) },
                        { label: "Gross Profit", values: numericRows(statements.grossProfit), bold: true },
                        { label: "OpEx", values: numericRows(statements.opex) },
                        { label: "EBIT", values: numericRows(statements.ebit), bold: true },
                        { label: "Taxes", values: numericRows(statements.taxes) },
                        { label: "Net Income", values: numericRows(statements.netIncome), bold: true },
                      ].map((row) => (
                        <tr
                          key={row.label}
                          className={row.bold ? "bg-[#f9f9f9]" : ""}
                        >
                          <td
                            className={`px-3 py-2 text-[#0F0B0B] ${
                              row.bold ? "font-semibold" : ""
                            }`}
                          >
                            {row.label}
                          </td>
                          {row.values.map((value, idx) => (
                            <td
                              key={idx}
                              className={`px-3 py-2 text-right text-[#0F0B0B] ${
                                row.bold ? "font-semibold" : ""
                              }`}
                            >
                              ${(value / 1000000).toFixed(1)}M
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </Card>
          </div>
        )}

        {/* Variance Tab */}
        {activeTab === "variance" && variances && (
          <div className="space-y-6">
            <Card className="bg-white">
              <div className="p-4">
                <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                  Budget vs Actual
                </h3>
                <div className="overflow-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#f0f0f0]">
                        <th className="px-3 py-2 text-left font-semibold text-[#0F0B0B]">
                          Period
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-[#0F0B0B]">
                          Budget
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-[#0F0B0B]">
                          Actual
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-[#0F0B0B]">
                          Variance
                        </th>
                        <th className="px-3 py-2 text-center font-semibold text-[#0F0B0B]">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#f0f0f0]">
                      {variances.map((row) => (
                        <tr key={row.period} className="hover:bg-[#f9f9f9]">
                          <td className="px-3 py-2 text-[#0F0B0B]">
                            Period {row.period}
                          </td>
                          <td className="px-3 py-2 text-right text-[#0F0B0B]">
                            ${row.budget.toFixed(0)}
                          </td>
                          <td className="px-3 py-2 text-right text-[#0F0B0B]">
                            ${row.actual.toFixed(0)}
                          </td>
                          <td
                            className={`px-3 py-2 text-right font-semibold ${
                              row.favorable
                                ? "text-[#86BC24]"
                                : "text-red-600"
                            }`}
                          >
                            ${row.variance.toFixed(0)} ({row.variancePct.toFixed(1)}%)
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Badge
                              variant={row.favorable ? "success" : "warning"}
                            >
                              {row.favorable ? "Favorable" : "Unfavorable"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </Card>
          </div>
        )}

        {/* Forecast Tab */}
        {activeTab === "forecast" && forecasts && (
          <div className="space-y-6">
            <Card className="bg-white">
              <div className="p-4">
                <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                  Financial Forecast
                </h3>
                <div className="overflow-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#f0f0f0]">
                        <th className="px-3 py-2 text-left font-semibold text-[#0F0B0B]">
                          Period
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-[#0F0B0B]">
                          Revenue
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-[#0F0B0B]">
                          Margin
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-[#0F0B0B]">
                          EBIT
                        </th>
                        <th className="px-3 py-2 text-center font-semibold text-[#0F0B0B]">
                          Confidence
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#f0f0f0]">
                      {forecasts.map((row) => (
                        <tr key={row.period} className="hover:bg-[#f9f9f9]">
                          <td className="px-3 py-2 text-[#0F0B0B]">
                            Year {row.period}
                          </td>
                          <td className="px-3 py-2 text-right text-[#0F0B0B]">
                            ${(row.revenue / 1000000).toFixed(1)}M
                          </td>
                          <td className="px-3 py-2 text-right text-[#0F0B0B]">
                            {(row.margin * 100).toFixed(1)}%
                          </td>
                          <td className="px-3 py-2 text-right text-[#0F0B0B]">
                            ${(row.ebit / 1000000).toFixed(1)}M
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Badge variant="info">
                              {(row.confidence * 100).toFixed(0)}%
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </Card>
          </div>
        )}

        {/* Assumptions Tab */}
        {activeTab === "assumptions" && assumptions && (
          <div className="space-y-6">
            <Card className="bg-white">
              <div className="p-4">
                <h3 className="mb-3 text-base font-semibold text-[#0F0B0B]">
                  Model Assumptions
                </h3>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {Object.entries(assumptions).map(([key, value]) => (
                    <div key={key} className="rounded-lg bg-[#f9f9f9] p-3">
                      <p className="text-xs text-[#4C4C4C]">
                        {key
                          .replace(/([A-Z])/g, " $1")
                          .replace(/^./, (str) => str.toUpperCase())}
                      </p>
                      <p className="mt-1 text-lg font-semibold text-[#0F0B0B]">
                        {typeof value === "number" && value < 1
                          ? `${(value * 100).toFixed(1)}%`
                          : typeof value === "number" && value > 1000
                          ? `$${(value / 1000000).toFixed(1)}M`
                          : value}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
