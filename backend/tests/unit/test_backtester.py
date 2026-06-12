from datetime import datetime, timedelta, timezone

from app.backtest.engine import Backtester, BacktestMarket
from app.backtest.strategies import (
    BacktestSnapshot,
    EntryDecision,
    LongshotFadeStrategy,
    MeanReversionStrategy,
)


def make_snapshots(prices: list[float], start: datetime | None = None) -> list[BacktestSnapshot]:
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        BacktestSnapshot(
            ts=(start + timedelta(hours=i)).isoformat(),
            yes_price=p,
            best_bid=max(p - 0.01, 0.01),
            best_ask=min(p + 0.01, 0.99),
            liquidity=50_000,
            volume_24h=10_000,
            hours_to_resolution=float(len(prices) - i),
        )
        for i, p in enumerate(prices)
    ]


class AlwaysYesStrategy:
    """Test double: enter buy_yes once at the 5th snapshot."""

    name = "always_yes"

    def decide(self, market_id: str, history: list[BacktestSnapshot]) -> EntryDecision:
        if len(history) == 5:
            return EntryDecision(True, "buy_yes", kelly=0.10, predicted_prob=0.9, edge_score=80)
        return EntryDecision(False)


class TestBacktester:
    def test_winning_trade_grows_equity(self):
        market = BacktestMarket(
            market_id="m1", question="Q?", outcome=1,
            snapshots=make_snapshots([0.5] * 20),
            resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        result = Backtester(starting_bankroll=10_000).run([market], AlwaysYesStrategy())
        assert result.metrics["n_trades"] == 1
        assert result.metrics["final_equity"] > 10_000
        assert result.metrics["win_rate"] == 1.0

    def test_losing_trade_shrinks_equity(self):
        market = BacktestMarket(
            market_id="m1", question="Q?", outcome=0,
            snapshots=make_snapshots([0.5] * 20),
            resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        result = Backtester(starting_bankroll=10_000).run([market], AlwaysYesStrategy())
        assert result.metrics["final_equity"] < 10_000
        assert result.metrics["win_rate"] == 0.0

    def test_stake_respects_max_risk(self):
        market = BacktestMarket(
            market_id="m1", question="Q?", outcome=1,
            snapshots=make_snapshots([0.5] * 20),
            resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        result = Backtester(starting_bankroll=10_000, max_risk_pct=2.0).run([market], AlwaysYesStrategy())
        trade = result.trades[0]
        assert trade.stake <= 10_000 * 0.02 + 1e-6

    def test_ev_accuracy_reported(self):
        market = BacktestMarket(
            market_id="m1", question="Q?", outcome=1,
            snapshots=make_snapshots([0.5] * 20),
            resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        result = Backtester().run([market], AlwaysYesStrategy())
        assert result.metrics["ev_accuracy"]["n"] == 1

    def test_no_entries_flat_curve(self):
        market = BacktestMarket(
            market_id="m1", question="Q?", outcome=1,
            snapshots=make_snapshots([0.5] * 3),  # too short for strategies
            resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        result = Backtester(starting_bankroll=5_000).run([market], MeanReversionStrategy())
        assert result.metrics["n_trades"] == 0
        assert result.metrics["final_equity"] == 5_000


class TestStrategies:
    def test_mean_reversion_fades_jump(self):
        # steady 0.50 then a sharp run-up to 0.62 within the lookback window
        prices = [0.50] * 12 + [0.52, 0.55, 0.58, 0.62]
        history = make_snapshots(prices)
        decision = MeanReversionStrategy(jump_threshold=0.08, lookback=4).decide("m1", history)
        assert decision.enter
        assert decision.direction == "buy_no"  # fading an up-move

    def test_mean_reversion_ignores_quiet_market(self):
        history = make_snapshots([0.50] * 20)
        decision = MeanReversionStrategy().decide("m1", history)
        assert not decision.enter

    def test_longshot_fade_buys_no_on_cheap_yes(self):
        history = make_snapshots([0.06] * 5)
        decision = LongshotFadeStrategy().decide("m1", history)
        assert decision.enter
        assert decision.direction == "buy_no"

    def test_longshot_fade_ignores_mid_prices(self):
        history = make_snapshots([0.40] * 5)
        decision = LongshotFadeStrategy().decide("m1", history)
        assert not decision.enter
