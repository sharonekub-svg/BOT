import numpy as np

from app.backtest.metrics import (
    cagr,
    daily_returns,
    ev_accuracy,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    summarize,
    win_rate,
)


class TestReturns:
    def test_daily_returns(self):
        rets = daily_returns([100, 110, 99])
        assert abs(rets[0] - 0.10) < 1e-9
        assert abs(rets[1] - (-0.10)) < 1e-9

    def test_daily_returns_does_not_mutate_input(self):
        curve = [0.0, 100.0, 110.0]
        daily_returns(curve)
        assert curve == [0.0, 100.0, 110.0]


class TestRatios:
    def test_sharpe_none_for_flat_curve(self):
        assert sharpe_ratio([100, 100, 100, 100]) is None

    def test_sharpe_positive_for_uptrend(self):
        curve = list(np.linspace(100, 200, 50) + np.random.RandomState(0).normal(0, 1, 50))
        assert sharpe_ratio(curve) > 0

    def test_sortino_none_without_downside(self):
        assert sortino_ratio([100, 101, 102, 103]) is None


class TestDrawdown:
    def test_known_drawdown(self):
        assert abs(max_drawdown([100, 120, 60, 80]) - 0.5) < 1e-9

    def test_no_drawdown_monotonic(self):
        assert max_drawdown([100, 110, 120]) == 0.0


class TestCagr:
    def test_doubling_in_a_year(self):
        assert abs(cagr([100, 200], 365) - 1.0) < 1e-9

    def test_invalid_inputs(self):
        assert cagr([100], 365) is None
        assert cagr([100, 200], 0) is None


class TestTradeStats:
    def test_win_rate(self):
        assert abs(win_rate([5, -3, 10]) - 2 / 3) < 1e-9
        assert win_rate([]) is None

    def test_profit_factor(self):
        assert abs(profit_factor([10, -5]) - 2.0) < 1e-9
        assert profit_factor([10, 5]) is None  # no losses


class TestEVAccuracy:
    def test_perfect_predictions(self):
        report = ev_accuracy([1.0, 0.0, 1.0], [1, 0, 1])
        assert report["brier"] == 0.0
        assert report["directional_hit_rate"] == 1.0
        assert report["n"] == 3

    def test_coin_flip_predictions(self):
        report = ev_accuracy([0.5, 0.5], [1, 0])
        assert abs(report["brier"] - 0.25) < 1e-9


class TestSummary:
    def test_summary_shape(self):
        summary = summarize(
            equity_curve=[10_000, 10_500, 10_200, 11_000],
            n_days=30,
            trade_pnls=[500, -300, 800],
            predicted_probs=[0.7, 0.4],
            outcomes=[1, 0],
        )
        for key in ("final_equity", "total_return", "sharpe", "max_drawdown",
                    "cagr", "win_rate", "profit_factor", "n_trades", "ev_accuracy"):
            assert key in summary
        assert summary["n_trades"] == 3
        assert summary["final_equity"] == 11_000
