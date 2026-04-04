"use client";

import dynamic from "next/dynamic";

type DashboardData = {
  kpis: Array<{ id: string; label: string; value: string | number }>;
  charts: Array<{ id: string; title: string; labels: string[]; datasets: Array<{ label: string; data: number[] }> }>;
  tables: Array<{ id: string; title: string; columns: string[]; rows: Array<Array<string | number | boolean>> }>;
};

const DashboardBarChart = dynamic(() => import("@/components/models/ModelDashboardChart"), {
  ssr: false,
  loading: () => <p className="text-xs text-[var(--text-muted)]">Loading chart...</p>,
});

export function ModelDashboard({ data }: { data: DashboardData | undefined }) {
  if (!data) {
    return (
      <div className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 text-sm text-[var(--primary-700)] shadow-sm">
        Loading dashboard...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        {data.kpis.map((kpi) => (
          <div
            key={kpi.id}
            className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 shadow-sm"
          >
            <p className="text-xs text-[var(--primary-600)]">{kpi.label}</p>
            <p className="text-xl font-semibold">{kpi.value}</p>
          </div>
        ))}
      </div>
      {data.charts.map((chart) => (
        <div
          key={chart.id}
          className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 shadow-sm"
        >
          <h3 className="mb-2 text-base font-semibold">{chart.title}</h3>
          <DashboardBarChart labels={chart.labels} datasets={chart.datasets} />
        </div>
      ))}
      {data.tables.map((table) => (
        <div
          key={table.id}
          className="rounded-lg border border-[color:color-mix(in_srgb,var(--primary-700)_20%,transparent)] bg-white p-4 shadow-sm"
        >
          <h3 className="mb-2 text-base font-semibold">{table.title}</h3>
          <div className="overflow-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-[var(--primary-600)]">
                  {table.columns.map((col) => (
                    <th key={col} className="px-2 py-1">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, idx) => (
                  <tr key={idx} className="border-t border-[color:color-mix(in_srgb,var(--primary-100)_70%,white)]">
                    {row.map((cell, cidx) => (
                      <td key={`${idx}:${cidx}`} className="px-2 py-1">
                        {String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
