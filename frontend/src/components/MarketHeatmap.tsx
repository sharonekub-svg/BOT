"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { fmtCompact, fmtProb, fmtSignedPct, heatColor } from "@/lib/format";
import type { HeatmapTile } from "@/lib/types";
import Panel from "./Panel";

export default function MarketHeatmap() {
  const { data } = useSWR<{ tiles: HeatmapTile[] }>("/api/v1/markets/heatmap?limit=60", fetcher, {
    refreshInterval: 30_000,
  });
  const tiles = data?.tiles ?? [];

  return (
    <Panel
      title="Market Heatmap — 24h probability change"
      right={<span className="text-xs text-slate-500">top {tiles.length} by volume</span>}
    >
      {tiles.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">No market data yet.</p>
      ) : (
        <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-6 lg:grid-cols-10">
          {tiles.map((tile) => (
            <div
              key={tile.id}
              className={`group relative aspect-square rounded ${heatColor(tile.change)} p-1 transition-transform hover:z-10 hover:scale-110`}
              title={`${tile.question}\n${fmtProb(tile.yes_price)} (${fmtSignedPct(tile.change)}) — vol ${fmtCompact(tile.volume_24h)}`}
            >
              <div className="flex h-full flex-col justify-between overflow-hidden">
                <span className="truncate text-[8px] leading-tight text-white/70">
                  {tile.category}
                </span>
                <div>
                  <div className="font-mono text-[10px] font-bold text-white">
                    {fmtProb(tile.yes_price)}
                  </div>
                  <div className="font-mono text-[8px] text-white/80">
                    {fmtSignedPct(tile.change, 0)}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
