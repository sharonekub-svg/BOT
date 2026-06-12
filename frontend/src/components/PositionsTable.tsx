"use client";

import useSWR from "swr";
import { fetcher, post } from "@/lib/api";
import { fmtUsd, pnlColor, timeAgo } from "@/lib/format";
import type { Position } from "@/lib/types";
import Panel from "./Panel";

export default function PositionsTable() {
  const { data, mutate } = useSWR<{ positions: Position[] }>("/api/v1/positions", fetcher, {
    refreshInterval: 10_000,
  });
  const rows = data?.positions ?? [];

  const closePosition = async (id: number) => {
    try {
      await post(`/api/v1/positions/${id}/close`);
      await mutate();
    } catch {
      /* surfaced via next refresh */
    }
  };

  return (
    <Panel title="Open Positions" right={<span className="text-xs text-slate-500">{rows.length}</span>}>
      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500">No open positions.</p>
      ) : (
        <div className="max-h-[300px] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-panel text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="pb-2 pr-2">Market</th>
                <th className="pb-2 pr-2">Side</th>
                <th className="pb-2 pr-2">Qty</th>
                <th className="pb-2 pr-2">Avg</th>
                <th className="pb-2 pr-2">Now</th>
                <th className="pb-2 pr-2">Value</th>
                <th className="pb-2 pr-2">uPnL</th>
                <th className="pb-2 pr-2">Age</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {rows.map((p) => (
                <tr key={p.id} className="hover:bg-slate-800/30">
                  <td className="max-w-[260px] truncate py-2 pr-2 text-slate-200" title={p.question}>
                    {p.question}
                  </td>
                  <td className="py-2 pr-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                        p.outcome === "YES"
                          ? "bg-emerald-500/15 text-emerald-400"
                          : "bg-rose-500/15 text-rose-400"
                      }`}
                    >
                      {p.outcome}
                    </span>
                  </td>
                  <td className="py-2 pr-2 font-mono text-xs">{p.qty.toFixed(0)}</td>
                  <td className="py-2 pr-2 font-mono text-xs">{p.avg_price.toFixed(2)}</td>
                  <td className="py-2 pr-2 font-mono text-xs">
                    {p.current_price !== null ? p.current_price.toFixed(2) : "–"}
                  </td>
                  <td className="py-2 pr-2 font-mono text-xs">{fmtUsd(p.value, 0)}</td>
                  <td className={`py-2 pr-2 font-mono text-xs ${pnlColor(p.unrealized_pnl)}`}>
                    {p.unrealized_pnl !== null ? fmtUsd(p.unrealized_pnl, 0) : "–"}
                  </td>
                  <td className="py-2 pr-2 text-xs text-slate-500">{timeAgo(p.opened_at)}</td>
                  <td className="py-2 text-right">
                    <button
                      onClick={() => closePosition(p.id)}
                      className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:border-rose-500 hover:text-rose-400"
                    >
                      CLOSE
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
