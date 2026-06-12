"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { edgeColor, fmtCompact, fmtProb, fmtSignedPct, timeAgo } from "@/lib/format";
import type { Opportunity } from "@/lib/types";
import Panel from "./Panel";

function DirectionBadge({ direction }: { direction: string }) {
  const isYes = direction === "buy_yes";
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
        isYes ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400"
      }`}
    >
      {isYes ? "BUY YES" : "BUY NO"}
    </span>
  );
}

function EdgeBar({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded bg-slate-800">
        <div
          className={`h-full rounded ${score >= 75 ? "bg-emerald-500" : score >= 50 ? "bg-amber-500" : "bg-slate-600"}`}
          style={{ width: `${Math.min(score, 100)}%` }}
        />
      </div>
      <span className={`font-mono text-sm font-semibold ${edgeColor(score)}`}>{score.toFixed(0)}</span>
    </div>
  );
}

export default function OpportunityTable() {
  const { data, error } = useSWR<{ opportunities: Opportunity[] }>(
    "/api/v1/opportunities?limit=25",
    fetcher,
    { refreshInterval: 10_000 },
  );
  const rows = data?.opportunities ?? [];

  return (
    <Panel
      title="EV Opportunities — Edge Rankings"
      right={<span className="text-xs text-slate-500">{rows.length} active</span>}
    >
      {error ? (
        <p className="py-6 text-center text-sm text-rose-400">API unreachable</p>
      ) : rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500">
          No active signals yet — start the worker or seed demo data.
        </p>
      ) : (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-panel text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="pb-2 pr-2">Market</th>
                <th className="pb-2 pr-2">Edge</th>
                <th className="pb-2 pr-2">Side</th>
                <th className="pb-2 pr-2">Implied → Fair</th>
                <th className="pb-2 pr-2">EV</th>
                <th className="pb-2 pr-2">Kelly</th>
                <th className="pb-2 pr-2">Liq</th>
                <th className="pb-2">Age</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {rows.map((o) => (
                <tr key={o.signal_id} className="hover:bg-slate-800/30">
                  <td className="max-w-[280px] py-2 pr-2">
                    <div className="truncate text-slate-200" title={o.question}>
                      {o.question}
                    </div>
                    <div className="text-[10px] text-slate-500">{o.category ?? "uncategorized"}</div>
                  </td>
                  <td className="py-2 pr-2">
                    <EdgeBar score={o.edge_score} />
                  </td>
                  <td className="py-2 pr-2">
                    <DirectionBadge direction={o.direction} />
                  </td>
                  <td className="py-2 pr-2 font-mono text-xs text-slate-300">
                    {fmtProb(o.implied_prob)} → <span className="text-sky-400">{fmtProb(o.fair_prob)}</span>
                  </td>
                  <td className={`py-2 pr-2 font-mono text-xs ${(o.expected_value ?? 0) > 0 ? "text-emerald-400" : "text-slate-400"}`}>
                    {fmtSignedPct(o.expected_value)}
                  </td>
                  <td className="py-2 pr-2 font-mono text-xs text-slate-400">
                    {o.kelly_size !== null ? `${(o.kelly_size * 100).toFixed(1)}%` : "–"}
                  </td>
                  <td className="py-2 pr-2 font-mono text-xs text-slate-400">{fmtCompact(o.liquidity)}</td>
                  <td className="py-2 text-xs text-slate-500">{timeAgo(o.ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
