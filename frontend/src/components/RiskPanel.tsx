"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { fmtUsd, pnlColor } from "@/lib/format";
import type { RiskReport } from "@/lib/types";
import Panel from "./Panel";

function LimitBar({ label, used, limit, unit = "%" }: { label: string; used: number; limit: number; unit?: string }) {
  const ratio = limit > 0 ? Math.min(used / limit, 1) : 0;
  const color = ratio > 0.85 ? "bg-rose-500" : ratio > 0.6 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono text-slate-300">
          {used.toFixed(1)}{unit} <span className="text-slate-600">/ {limit.toFixed(0)}{unit}</span>
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-slate-800">
        <div className={`h-full rounded ${color}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}

export default function RiskPanel() {
  const { data } = useSWR<RiskReport>("/api/v1/risk", fetcher, { refreshInterval: 15_000 });
  if (!data) {
    return (
      <Panel title="Risk Exposure">
        <p className="py-8 text-center text-sm text-slate-500">Loading…</p>
      </Panel>
    );
  }
  return (
    <Panel
      title="Risk Exposure"
      right={
        data.circuit_breaker_tripped ? (
          <span className="rounded bg-rose-500/15 px-2 py-0.5 text-[10px] font-bold text-rose-400">
            CIRCUIT BREAKER
          </span>
        ) : (
          <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-400">
            HEALTHY
          </span>
        )
      }
    >
      <div className="space-y-3">
        <LimitBar label="Total exposure" used={data.total_exposure_pct} limit={data.limits.max_total_exposure_pct} />
        <LimitBar label="Drawdown" used={data.drawdown_pct} limit={data.limits.max_drawdown_pct} />
        <LimitBar
          label="Open positions"
          used={data.open_positions}
          limit={data.limits.max_open_positions}
          unit=""
        />
        <div className="flex items-center justify-between border-t border-slate-800 pt-2 text-xs">
          <span className="text-slate-400">Daily P&L</span>
          <span className={`font-mono ${pnlColor(data.daily_pnl)}`}>{fmtUsd(data.daily_pnl)}</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400">Per-trade risk cap</span>
          <span className="font-mono text-slate-300">
            {data.limits.max_risk_per_trade_pct}% · {data.limits.kelly_fraction}× Kelly
          </span>
        </div>
        {data.warnings.length > 0 && (
          <ul className="space-y-1 rounded border border-rose-900/50 bg-rose-950/30 p-2">
            {data.warnings.map((w) => (
              <li key={w} className="text-xs text-rose-400">⚠ {w}</li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
