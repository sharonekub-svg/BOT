"use client";

import useSWR from "swr";
import AllocationChart from "@/components/AllocationChart";
import ArbitragePanel from "@/components/ArbitragePanel";
import LiveFeed from "@/components/LiveFeed";
import MarketHeatmap from "@/components/MarketHeatmap";
import OpportunityTable from "@/components/OpportunityTable";
import PnLChart from "@/components/PnLChart";
import PositionsTable from "@/components/PositionsTable";
import RiskPanel from "@/components/RiskPanel";
import StatCard from "@/components/StatCard";
import { fetcher } from "@/lib/api";
import { fmtPct, fmtUsd, pnlColor } from "@/lib/format";
import type { Portfolio, SystemStatus } from "@/lib/types";
import { useFeed } from "@/lib/useWebSocket";

function ModePill({ status }: { status?: SystemStatus }) {
  if (!status) return null;
  const live = status.trading_mode === "live";
  return (
    <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider">
      <span
        className={`rounded px-2 py-1 ${
          live ? "bg-rose-500/15 text-rose-400" : "bg-sky-500/15 text-sky-400"
        }`}
      >
        {status.trading_mode} mode
      </span>
      <span
        className={`rounded px-2 py-1 ${
          status.auto_trade_enabled ? "bg-emerald-500/15 text-emerald-400" : "bg-slate-700/40 text-slate-400"
        }`}
      >
        auto-trade {status.auto_trade_enabled ? "on" : "off"}
      </span>
      <span
        className={`rounded px-2 py-1 ${
          status.ai_enabled ? "bg-violet-500/15 text-violet-400" : "bg-slate-700/40 text-slate-400"
        }`}
      >
        AI {status.ai_enabled ? "on" : "off"}
      </span>
    </div>
  );
}

export default function Dashboard() {
  const { data: portfolio } = useSWR<Portfolio>("/api/v1/portfolio", fetcher, {
    refreshInterval: 10_000,
  });
  const { data: status } = useSWR<SystemStatus>("/api/v1/status", fetcher, {
    refreshInterval: 30_000,
  });
  const { events, connected } = useFeed();

  const totalPnl =
    portfolio !== undefined ? portfolio.equity - portfolio.starting_bankroll : undefined;
  const dayPnl =
    portfolio !== undefined ? portfolio.realized_pnl_today + portfolio.unrealized_pnl : undefined;

  return (
    <main className="mx-auto max-w-[1600px] px-4 py-5">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">
            Polymarket <span className="text-emerald-400">Edge</span>
          </h1>
          <p className="text-xs text-slate-500">
            {status
              ? `${status.counts.markets ?? 0} markets · ${status.counts.snapshots ?? 0} snapshots · ${status.counts.signals ?? 0} signals · ${status.counts.ai_analyses ?? 0} AI analyses`
              : "connecting to API…"}
          </p>
        </div>
        <ModePill status={status} />
      </header>

      {/* KPI row */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Equity" value={fmtUsd(portfolio?.equity)} sub={portfolio ? `start ${fmtUsd(portfolio.starting_bankroll)}` : undefined} />
        <StatCard
          label="Total P&L"
          value={fmtUsd(totalPnl)}
          valueClass={pnlColor(totalPnl)}
        />
        <StatCard
          label="P&L Today"
          value={fmtUsd(dayPnl)}
          valueClass={pnlColor(dayPnl)}
        />
        <StatCard label="Exposure" value={fmtUsd(portfolio?.exposure)} sub={portfolio ? `cash ${fmtUsd(portfolio.cash)}` : undefined} />
        <StatCard
          label="Drawdown"
          value={portfolio !== undefined ? fmtPct(portfolio.drawdown) : "–"}
          valueClass={portfolio !== undefined && portfolio.drawdown > 0.1 ? "text-rose-400" : "text-slate-100"}
        />
        <StatCard label="Open Positions" value={portfolio !== undefined ? String(portfolio.open_positions) : "–"} />
      </div>

      {/* main grid */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <OpportunityTable />
        </div>
        <LiveFeed events={events} connected={connected} />

        <PnLChart />
        <AllocationChart />
        <RiskPanel />

        <div className="xl:col-span-2">
          <PositionsTable />
        </div>
        <ArbitragePanel />

        <div className="xl:col-span-3">
          <MarketHeatmap />
        </div>
      </div>

      <footer className="mt-6 pb-4 text-center text-[10px] text-slate-600">
        Research &amp; portfolio tooling — not financial advice. Trading prediction markets involves
        substantial risk; verify the legality of trading in your jurisdiction.
      </footer>
    </main>
  );
}
