"use client";

import useSWR from "swr";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { fetcher } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import type { RiskReport } from "@/lib/types";
import Panel from "./Panel";

const COLORS = ["#10b981", "#0ea5e9", "#f59e0b", "#8b5cf6", "#f43f5e", "#14b8a6", "#eab308", "#64748b"];

export default function AllocationChart() {
  const { data } = useSWR<RiskReport>("/api/v1/risk", fetcher, { refreshInterval: 30_000 });
  const entries = Object.entries(data?.exposure_by_category ?? {});
  const chartData = entries.map(([name, value]) => ({ name, value }));
  const cash = data ? Math.max(data.cash, 0) : 0;
  if (data && cash > 0) chartData.push({ name: "cash", value: cash });

  return (
    <Panel title="Portfolio Allocation">
      {chartData.length === 0 ? (
        <p className="py-10 text-center text-sm text-slate-500">No exposure yet.</p>
      ) : (
        <div className="flex items-center gap-2">
          <div className="h-44 w-1/2">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={chartData} dataKey="value" nameKey="name" innerRadius={36} outerRadius={64} strokeWidth={0}>
                  {chartData.map((entry, i) => (
                    <Cell
                      key={entry.name}
                      fill={entry.name === "cash" ? "#1e293b" : COLORS[i % COLORS.length]}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 }}
                  formatter={(value: number | string, name: string) => [fmtUsd(Number(value)), name]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="w-1/2 space-y-1 text-xs">
            {chartData.map((entry, i) => (
              <li key={entry.name} className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-slate-300">
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ background: entry.name === "cash" ? "#475569" : COLORS[i % COLORS.length] }}
                  />
                  {entry.name}
                </span>
                <span className="font-mono text-slate-400">{fmtUsd(entry.value)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
