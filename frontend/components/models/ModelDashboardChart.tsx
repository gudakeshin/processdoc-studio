"use client";

import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip,
} from "chart.js";
import { Bar } from "react-chartjs-2";

ChartJS.register(BarElement, CategoryScale, LinearScale, Tooltip, Legend);

export default function ModelDashboardChart({
  labels,
  datasets,
}: {
  labels: string[];
  datasets: Array<{ label: string; data: number[] }>;
}) {
  return (
    <div className="relative h-60">
      <Bar
        data={{
          labels,
          datasets: datasets.map((d) => ({
            label: d.label,
            data: d.data,
          })),
        }}
        options={{ responsive: true, maintainAspectRatio: false }}
      />
    </div>
  );
}
