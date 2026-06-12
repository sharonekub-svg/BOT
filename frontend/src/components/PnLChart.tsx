"use client";

import useSWR from "swr";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetcher } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import type { PortfolioPoint } from "@/lib/types";
import Panel from "./Panel";

export default function PnLChart() {
  const { data } = useSWR<{ points: PortfolioPoint[] }>(
    "/api/v1/portfolio/history?hours=168",
    fetcher,
    { refreshInterval: 30_000 },
  );
  const points = (data?.points ?? []).map((p) => ({
    ...p,
    label: new Date(p.ts).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
  }));

  return (
    <Panel title="Equity — 7 days">
      {points.length < 2 ? (
        <p className="py-10 text-center text-sm text-slate-500">Not enough history yet.</p>
      ) : (
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
              <defs>
                <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="label" tick={{ fill: "#64748b", fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={40} />
              <YAxis
                domain={["auto", "auto"]}
                tick={{ fill: "#64748b", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={(v: number) => fmtUsd(v)}
              />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#94a3b8" }}
                formatter={(value: number | string) => [fmtUsd(Number(value)), "equity"]}
              />
              <Area type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2} fill="url(#equityFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  );
}
