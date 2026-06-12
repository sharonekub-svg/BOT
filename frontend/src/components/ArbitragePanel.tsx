"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { ArbitrageRow } from "@/lib/types";
import Panel from "./Panel";

export default function ArbitragePanel() {
  const { data } = useSWR<{ arbitrage: ArbitrageRow[] }>("/api/v1/arbitrage", fetcher, {
    refreshInterval: 15_000,
  });
  const rows = data?.arbitrage ?? [];

  return (
    <Panel title="Arbitrage" right={<span className="text-xs text-slate-500">{rows.length} live</span>}>
      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">No live arbitrage — books are efficient right now.</p>
      ) : (
        <ul className="max-h-56 space-y-2 overflow-auto">
          {rows.map((row) => (
            <li key={row.id} className="rounded border border-emerald-900/40 bg-emerald-950/20 p-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-400">
                  {row.kind.replace(/_/g, " ")}
                </span>
                <span className="font-mono text-sm font-semibold text-emerald-300">
                  +{(row.net_edge * 100).toFixed(2)}%
                </span>
              </div>
              <p className="mt-1 truncate text-xs text-slate-400" title={row.description}>
                {row.description}
              </p>
              <div className="mt-1 text-[10px] text-slate-600">
                {row.market_ids.length} market{row.market_ids.length > 1 ? "s" : ""} · {timeAgo(row.ts)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
