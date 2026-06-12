"""Event-driven backtester over stored market snapshots.

Walks history chronologically per market, lets a strategy open positions
(at the executable ask, fee- and slippage-adjusted), settles them at market
resolution, and produces an equity curve + the full metrics report.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.backtest.metrics import summarize
from app.backtest.strategies import BacktestSnapshot, Strategy
from app.core.utils import as_utc, now_utc
from app.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class BacktestMarket:
    market_id: str
    question: str
    outcome: int                       # 1 = YES, 0 = NO
    snapshots: list[BacktestSnapshot]  # chronological
    resolved_at: datetime | None = None


@dataclass
class SimTrade:
    market_id: str
    direction: str
    entry_price: float
    stake: float
    shares: float
    predicted_prob: float | None
    pnl: float | None = None


@dataclass
class BacktestResult:
    metrics: dict
    equity_curve: list[tuple[str, float]]
    trades: list[SimTrade] = field(default_factory=list)


class Backtester:
    def __init__(
        self,
        starting_bankroll: float = 10_000.0,
        kelly_multiplier: float = 0.25,
        max_risk_pct: float = 2.0,
        fee_rate: float = 0.0,
        slippage: float = 0.005,
        max_positions_per_market: int = 1,
    ) -> None:
        self.starting_bankroll = starting_bankroll
        self.kelly_multiplier = kelly_multiplier
        self.max_risk_pct = max_risk_pct
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.max_positions_per_market = max_positions_per_market

    def run(self, markets: list[BacktestMarket], strategy: Strategy) -> BacktestResult:
        # Collect candidate entries by replaying each market's history.
        entries: list[tuple[datetime, SimTrade, BacktestMarket]] = []
        for market in markets:
            taken = 0
            history: list[BacktestSnapshot] = []
            for snap in market.snapshots:
                history.append(snap)
                if taken >= self.max_positions_per_market:
                    continue
                decision = strategy.decide(market.market_id, history)
                if not decision.enter or decision.kelly <= 0:
                    continue
                price = self._entry_price(decision.direction, snap)
                if price is None or not (0.005 < price < 0.995):
                    continue
                ts = as_utc(datetime.fromisoformat(snap.ts))
                trade = SimTrade(
                    market_id=market.market_id,
                    direction=decision.direction,
                    entry_price=price,
                    stake=0.0,  # sized at execution time against current equity
                    shares=0.0,
                    predicted_prob=decision.predicted_prob,
                )
                trade._kelly = min(decision.kelly * self.kelly_multiplier, self.max_risk_pct / 100.0)  # type: ignore[attr-defined]
                entries.append((ts, trade, market))
                taken += 1

        # Execute chronologically against a single bankroll.
        entries.sort(key=lambda e: e[0])
        equity = self.starting_bankroll
        cash = self.starting_bankroll
        curve: list[tuple[str, float]] = []
        open_trades: list[tuple[datetime, SimTrade, BacktestMarket]] = []
        executed: list[SimTrade] = []

        events: list[tuple[datetime, str, object]] = [(ts, "entry", (trade, market)) for ts, trade, market in entries]
        for market in markets:
            resolved_at = as_utc(market.resolved_at) if market.resolved_at else (
                as_utc(datetime.fromisoformat(market.snapshots[-1].ts)) if market.snapshots else None
            )
            if resolved_at is not None:
                events.append((resolved_at, "resolve", market))
        events.sort(key=lambda e: (e[0], 0 if e[1] == "entry" else 1))

        for ts, kind, payload in events:
            if kind == "entry":
                trade, market = payload  # type: ignore[misc]
                stake = equity * trade._kelly  # type: ignore[attr-defined]
                stake = min(stake, cash)
                if stake < 1.0:
                    continue
                fill = min(trade.entry_price + self.slippage, 0.999)
                trade.entry_price = fill
                trade.stake = round(stake, 2)
                trade.shares = round(stake / fill, 2)
                cash -= stake + stake * self.fee_rate
                open_trades.append((ts, trade, market))
                executed.append(trade)
            else:
                market = payload  # type: ignore[assignment]
                still_open = []
                for entry_ts, trade, trade_market in open_trades:
                    if trade_market.market_id != market.market_id:
                        still_open.append((entry_ts, trade, trade_market))
                        continue
                    won = (trade.direction == "buy_yes" and market.outcome == 1) or (
                        trade.direction == "buy_no" and market.outcome == 0
                    )
                    payout = trade.shares * (1.0 if won else 0.0)
                    trade.pnl = round(payout - trade.stake, 2)
                    cash += payout
                open_trades = still_open
                open_value = sum(t.stake for _, t, _ in open_trades)
                equity = cash + open_value
                curve.append((ts.isoformat(), round(equity, 2)))

        # Mark any unresolved opens flat at the end.
        equity = cash + sum(t.stake for _, t, _ in open_trades)
        if curve:
            curve.append((curve[-1][0], round(equity, 2)))
        else:
            curve = [(now_utc().isoformat(), round(equity, 2))]

        first_ts = events[0][0] if events else None
        last_ts = events[-1][0] if events else None
        n_days = max(((last_ts - first_ts).total_seconds() / 86400.0) if first_ts and last_ts else 1.0, 1.0)

        settled = [t for t in executed if t.pnl is not None]
        outcome_lookup = {m.market_id: m.outcome for m in markets}
        predicted = [t.predicted_prob for t in settled]
        # predicted prob is P(direction side wins): convert to P(YES) for scoring
        predicted_yes = [
            (p if t.direction == "buy_yes" else p)  # strategies already report P(YES)
            for t, p in zip(settled, predicted)
        ]
        outcomes = [outcome_lookup.get(t.market_id) for t in settled]

        metrics = summarize(
            equity_curve=[self.starting_bankroll] + [v for _, v in curve],
            n_days=n_days,
            trade_pnls=[t.pnl for t in settled],
            predicted_probs=predicted_yes,
            outcomes=outcomes,
        )
        return BacktestResult(metrics=metrics, equity_curve=curve, trades=executed)

    @staticmethod
    def _entry_price(direction: str, snap: BacktestSnapshot) -> float | None:
        if direction == "buy_yes":
            return snap.best_ask if snap.best_ask is not None else snap.yes_price
        bid = snap.best_bid if snap.best_bid is not None else snap.yes_price
        return 1.0 - bid if bid is not None else None
