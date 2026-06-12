"use client";

import { timeAgo } from "@/lib/format";
import type { FeedEvent } from "@/lib/types";
import Panel from "./Panel";

const EVENT_META: Record<string, { icon: string; label: string; color: string }> = {
  scan_complete: { icon: "📡", label: "Scan", color: "text-slate-400" },
  anomaly: { icon: "⚡", label: "Anomaly", color: "text-amber-400" },
  signals_updated: { icon: "🎯", label: "Signals", color: "text-sky-400" },
  arbitrage_found: { icon: "♻️", label: "Arbitrage", color: "text-emerald-400" },
  ai_analysis: { icon: "🧠", label: "AI", color: "text-violet-400" },
  trade: { icon: "💱", label: "Trade", color: "text-emerald-400" },
  portfolio: { icon: "💼", label: "Portfolio", color: "text-slate-400" },
  protections: { icon: "🛡️", label: "Protection", color: "text-rose-400" },
  graph_updated: { icon: "🕸️", label: "Graph", color: "text-slate-400" },
};

function describe(event: FeedEvent): string {
  const d = event.data as Record<string, any>;
  switch (event.type) {
    case "scan_complete":
      return `${d.markets} markets, ${d.snapshots} snapshots, ${d.anomalies} anomalies`;
    case "anomaly":
      return `${d.kind} on ${String(d.market_id).slice(0, 10)}… (sev ${d.severity})`;
    case "signals_updated":
      return `${d.count} active signals ranked`;
    case "arbitrage_found":
      return `${d.count} arbitrage opportunit${d.count === 1 ? "y" : "ies"}`;
    case "ai_analysis":
      return `${d.signal} ${Math.round((d.prob ?? 0) * 100)}% (conf ${Math.round((d.confidence ?? 0) * 100)}%) — ${d.question}`;
    case "trade":
      return `${d.side} ${d.qty} ${d.outcome} @ ${Number(d.price).toFixed(2)} (${d.reason}) — ${d.question}`;
    case "portfolio":
      return `equity $${Number(d.equity).toFixed(0)}, exposure $${Number(d.exposure).toFixed(0)}`;
    case "protections":
      return `${d.stop_losses} stops, ${d.hedges} hedges`;
    case "graph_updated":
      return `${d.nodes} nodes / ${d.edges} edges`;
    default:
      return JSON.stringify(d).slice(0, 80);
  }
}

export default function LiveFeed({ events, connected }: { events: FeedEvent[]; connected: boolean }) {
  return (
    <Panel
      title="Live Feed"
      right={
        <span className={`flex items-center gap-1.5 text-xs ${connected ? "text-emerald-400" : "text-rose-400"}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-rose-400"}`} />
          {connected ? "live" : "offline"}
        </span>
      }
      className="h-full"
    >
      {events.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">
          Waiting for events — start the worker to see the live pipeline.
        </p>
      ) : (
        <ul className="max-h-[420px] space-y-1.5 overflow-auto pr-1">
          {events.map((event, i) => {
            const meta = EVENT_META[event.type] ?? { icon: "•", label: event.type, color: "text-slate-400" };
            return (
              <li key={`${event.ts}-${i}`} className="flex items-start gap-2 rounded bg-slate-900/60 px-2 py-1.5">
                <span className="text-sm leading-5">{meta.icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={`text-[10px] font-bold uppercase tracking-wider ${meta.color}`}>
                      {meta.label}
                    </span>
                    <span className="shrink-0 text-[10px] text-slate-600">{timeAgo(event.ts)}</span>
                  </div>
                  <p className="truncate text-xs text-slate-400" title={describe(event)}>
                    {describe(event)}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
