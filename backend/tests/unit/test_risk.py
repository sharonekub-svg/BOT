from app.risk.manager import PortfolioState, RiskManager, TradeIntent
from app.risk.sizing import SizingInputs, size_position


def make_state(**overrides) -> PortfolioState:
    defaults = dict(
        equity=10_000.0,
        cash=8_000.0,
        total_exposure=2_000.0,
        exposure_by_market={},
        exposure_by_category={},
        open_positions=3,
        daily_pnl=0.0,
        peak_equity=10_000.0,
    )
    defaults.update(overrides)
    return PortfolioState(**defaults)


def make_intent(**overrides) -> TradeIntent:
    defaults = dict(
        market_id="m1",
        category="politics",
        direction="buy_yes",
        entry_price=0.5,
        kelly=0.2,
        edge_score=80.0,
        liquidity=50_000.0,
    )
    defaults.update(overrides)
    return TradeIntent(**defaults)


class TestSizing:
    def test_kelly_sizing_basic(self):
        result = size_position(SizingInputs(10_000, 0.04, 0.25, 2.0, 0.5, 1e9))
        # quarter kelly of 4% = 1% of 10k = $100
        assert abs(result.notional - 100.0) < 1e-6
        assert result.capped_by == "kelly"

    def test_max_risk_cap_binds(self):
        result = size_position(SizingInputs(10_000, 0.5, 0.5, 2.0, 0.5, 1e9))
        assert result.notional == 200.0  # 2% of 10k
        assert result.capped_by == "max_risk"

    def test_liquidity_cap_binds(self):
        result = size_position(SizingInputs(10_000, 0.5, 0.5, 2.0, 0.5, 1_000))
        assert result.notional == 50.0  # 5% of 1k pool
        assert result.capped_by == "liquidity"

    def test_zero_kelly_zero_size(self):
        result = size_position(SizingInputs(10_000, 0.0, 0.25, 2.0, 0.5, 1e9))
        assert result.notional == 0.0
        assert result.capped_by == "zero"


class TestTradeGate:
    def test_approves_good_trade(self):
        decision = RiskManager().evaluate_trade(make_state(), make_intent())
        assert decision.approved
        assert decision.notional > 0
        assert decision.shares > 0

    def test_rejects_low_edge(self):
        decision = RiskManager().evaluate_trade(make_state(), make_intent(edge_score=10))
        assert not decision.approved
        assert "edge score" in decision.reason

    def test_rejects_thin_market(self):
        decision = RiskManager().evaluate_trade(make_state(), make_intent(liquidity=50))
        assert not decision.approved
        assert "liquidity" in decision.reason

    def test_rejects_when_max_positions(self):
        state = make_state(open_positions=10_000)
        decision = RiskManager().evaluate_trade(state, make_intent())
        assert not decision.approved

    def test_rejects_after_daily_loss_limit(self):
        state = make_state(daily_pnl=-1_000.0)  # -10% vs default 5% limit
        decision = RiskManager().evaluate_trade(state, make_intent())
        assert not decision.approved
        assert "daily loss" in decision.reason

    def test_circuit_breaker_blocks_everything(self):
        manager = RiskManager()
        manager.circuit_breaker_tripped = True
        decision = manager.evaluate_trade(make_state(), make_intent())
        assert not decision.approved
        assert "circuit breaker" in decision.reason

    def test_market_exposure_cap(self):
        # already at the 10% per-market cap
        state = make_state(exposure_by_market={"m1": 1_000.0})
        decision = RiskManager().evaluate_trade(state, make_intent())
        assert not decision.approved
        assert "market exposure" in decision.reason

    def test_notional_never_exceeds_max_risk(self):
        decision = RiskManager().evaluate_trade(make_state(), make_intent(kelly=0.9))
        assert decision.approved
        assert decision.notional <= 10_000 * 0.02 + 1e-6


class TestHealth:
    def test_drawdown_trips_circuit_breaker(self):
        manager = RiskManager()
        state = make_state(equity=8_000.0, peak_equity=10_000.0)  # 20% DD vs 15% limit
        warnings = manager.check_portfolio_health(state)
        assert manager.circuit_breaker_tripped
        assert any("drawdown" in w for w in warnings)

    def test_healthy_portfolio_no_warnings(self):
        manager = RiskManager()
        warnings = manager.check_portfolio_health(make_state())
        assert warnings == []
        assert not manager.circuit_breaker_tripped

    def test_reset_circuit_breaker(self):
        manager = RiskManager()
        manager.circuit_breaker_tripped = True
        manager.reset_circuit_breaker()
        assert not manager.circuit_breaker_tripped


class TestStops:
    def test_stop_loss_threshold(self):
        manager = RiskManager()  # default 25%
        assert manager.stop_loss_hit(avg_price=0.40, current_price=0.29)
        assert not manager.stop_loss_hit(avg_price=0.40, current_price=0.35)

    def test_hedge_threshold(self):
        manager = RiskManager()  # default 15%
        assert manager.hedge_trigger_hit(avg_price=0.40, current_price=0.33)
        assert not manager.hedge_trigger_hit(avg_price=0.40, current_price=0.38)
