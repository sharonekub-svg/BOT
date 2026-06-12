from app.edge.engine import (
    FairEstimate,
    MarketState,
    combine_fair_estimates,
    evaluate_market,
    expected_value,
    kelly_fraction,
)


def make_state(**overrides) -> MarketState:
    defaults = dict(
        market_id="m1",
        implied_prob=0.50,
        best_bid=0.49,
        best_ask=0.51,
        liquidity=50_000,
        volume_24h=100_000,
        hours_to_resolution=24 * 14,
    )
    defaults.update(overrides)
    return MarketState(**defaults)


class TestEnsemble:
    def test_no_estimates_returns_implied_with_zero_confidence(self):
        fair, conf = combine_fair_estimates(0.4, [])
        assert fair == 0.4
        assert conf == 0.0

    def test_bullish_estimate_pulls_fair_up(self):
        fair, conf = combine_fair_estimates(0.4, [FairEstimate("ai", 0.6, 0.8)])
        assert 0.4 < fair < 0.6
        assert conf > 0

    def test_agreeing_estimates_raise_confidence(self):
        agreeing = [FairEstimate("ai", 0.6, 0.6), FairEstimate("ml", 0.62, 0.6)]
        disagreeing = [FairEstimate("ai", 0.6, 0.6), FairEstimate("ml", 0.3, 0.6)]
        _, conf_agree = combine_fair_estimates(0.45, agreeing)
        _, conf_disagree = combine_fair_estimates(0.45, disagreeing)
        assert conf_agree > conf_disagree

    def test_fair_clamped_to_valid_range(self):
        fair, _ = combine_fair_estimates(0.99, [FairEstimate("ai", 0.999, 1.0)])
        assert fair <= 0.99


class TestMath:
    def test_expected_value_positive_when_underpriced(self):
        # worth 0.6, costs 0.5 -> ROI 20%
        assert abs(expected_value(0.6, 0.5) - 0.2) < 1e-9

    def test_expected_value_with_fees(self):
        assert expected_value(0.6, 0.5, fee_rate=0.02) < expected_value(0.6, 0.5)

    def test_kelly_known_value(self):
        # fair 0.6 at price 0.5: f* = 0.6 - 0.4*0.5/0.5 = 0.2
        assert abs(kelly_fraction(0.6, 0.5) - 0.2) < 1e-9

    def test_kelly_zero_when_no_edge(self):
        assert kelly_fraction(0.5, 0.5) == 0.0
        assert kelly_fraction(0.4, 0.5) == 0.0  # negative edge clamps to 0


class TestEvaluate:
    def test_bullish_signal(self):
        result = evaluate_market(make_state(), [FairEstimate("ai", 0.65, 0.8)])
        assert result.direction == "buy_yes"
        assert result.expected_value > 0
        assert 0 < result.edge_score <= 100
        assert result.fair_prob > result.implied_prob

    def test_bearish_signal(self):
        result = evaluate_market(make_state(), [FairEstimate("ai", 0.35, 0.8)])
        assert result.direction == "buy_no"
        assert result.expected_value > 0

    def test_no_estimates_no_anomaly_capped(self):
        result = evaluate_market(make_state(), [])
        assert result.edge_score <= 25
        assert result.direction == "none"

    def test_bigger_mispricing_scores_higher(self):
        small = evaluate_market(make_state(), [FairEstimate("ai", 0.55, 0.8)])
        large = evaluate_market(make_state(), [FairEstimate("ai", 0.75, 0.8)])
        assert large.edge_score > small.edge_score

    def test_liquidity_contributes(self):
        thin = evaluate_market(make_state(liquidity=100), [FairEstimate("ai", 0.65, 0.8)])
        deep = evaluate_market(make_state(liquidity=200_000), [FairEstimate("ai", 0.65, 0.8)])
        assert deep.edge_score > thin.edge_score

    def test_components_present_and_bounded(self):
        result = evaluate_market(make_state(), [FairEstimate("ai", 0.65, 0.8)])
        for key in ("mispricing", "value", "confidence", "liquidity", "time", "anomaly"):
            assert key in result.components
            assert 0.0 <= result.components[key] <= 1.0

    def test_entry_price_uses_executable_side(self):
        result = evaluate_market(make_state(best_ask=0.53), [FairEstimate("ai", 0.7, 0.9)])
        assert result.entry_price == 0.53  # buys YES at the ask
