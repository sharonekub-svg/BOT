from app.edge.arbitrage import (
    binary_complement_arb,
    group_event_outcomes,
    implication_violation,
    multi_outcome_arb,
)


class TestBinaryComplement:
    def test_detects_underpriced_pair(self):
        arb = binary_complement_arb("m1", "Q?", ask_yes=0.48, ask_no=0.50, buffer=0.005)
        assert arb is not None
        assert arb.kind == "binary_complement"
        assert abs(arb.gross_edge - 0.02) < 1e-9
        assert abs(arb.net_edge - 0.015) < 1e-9
        assert len(arb.legs) == 2

    def test_no_arb_when_fairly_priced(self):
        assert binary_complement_arb("m1", "Q?", 0.50, 0.50) is None
        assert binary_complement_arb("m1", "Q?", 0.52, 0.50) is None

    def test_buffer_kills_marginal_edge(self):
        assert binary_complement_arb("m1", "Q?", 0.497, 0.50, buffer=0.005) is None

    def test_handles_missing_quotes(self):
        assert binary_complement_arb("m1", "Q?", None, 0.5) is None
        assert binary_complement_arb("m1", "Q?", 0.5, None) is None


class TestMultiOutcome:
    def test_long_basket(self):
        outcomes = [
            {"market_id": f"m{i}", "question": f"O{i}?", "ask": 0.30, "bid": 0.28}
            for i in range(3)
        ]
        arbs = multi_outcome_arb("ev1", outcomes, buffer=0.005)
        kinds = {a.kind for a in arbs}
        assert "multi_outcome_long" in kinds
        long = next(a for a in arbs if a.kind == "multi_outcome_long")
        assert abs(long.gross_edge - 0.10) < 1e-9
        assert all(leg.outcome == "YES" for leg in long.legs)

    def test_short_basket(self):
        outcomes = [
            {"market_id": f"m{i}", "question": f"O{i}?", "ask": 0.42, "bid": 0.40}
            for i in range(3)
        ]
        arbs = multi_outcome_arb("ev1", outcomes, buffer=0.005)
        short = next(a for a in arbs if a.kind == "multi_outcome_short")
        assert abs(short.gross_edge - 0.20) < 1e-9
        assert all(leg.outcome == "NO" for leg in short.legs)

    def test_no_arb_in_efficient_event(self):
        outcomes = [
            {"market_id": "a", "question": "A?", "ask": 0.51, "bid": 0.49},
            {"market_id": "b", "question": "B?", "ask": 0.51, "bid": 0.49},
        ]
        assert multi_outcome_arb("ev1", outcomes) == []


class TestImplication:
    def test_violation_detected(self):
        narrow = {"market_id": "n", "question": "X wins by 10+ points?", "bid": 0.60, "ask": 0.62}
        broad = {"market_id": "b", "question": "X wins?", "bid": 0.48, "ask": 0.50}
        arb = implication_violation(narrow, broad)
        assert arb is not None
        assert arb.kind == "cross_market"
        assert arb.gross_edge >= 0.02

    def test_consistent_prices_pass(self):
        narrow = {"market_id": "n", "question": "narrow?", "bid": 0.30, "ask": 0.32}
        broad = {"market_id": "b", "question": "broad?", "bid": 0.55, "ask": 0.57}
        assert implication_violation(narrow, broad) is None


class TestGrouping:
    def test_groups_neg_risk_events(self):
        markets = [
            {"market_id": "a", "question": "A", "event_id": "e1", "neg_risk": True, "ask": 0.3, "bid": 0.2},
            {"market_id": "b", "question": "B", "event_id": "e1", "neg_risk": True, "ask": 0.3, "bid": 0.2},
            {"market_id": "c", "question": "C", "event_id": "e2", "neg_risk": True, "ask": 0.3, "bid": 0.2},
            {"market_id": "d", "question": "D", "event_id": None, "neg_risk": True, "ask": 0.3, "bid": 0.2},
            {"market_id": "e", "question": "E", "event_id": "e3", "neg_risk": False, "ask": 0.3, "bid": 0.2},
        ]
        groups = group_event_outcomes(markets)
        assert len(groups) == 1
        assert groups[0].event_id == "e1"
        assert len(groups[0].markets) == 2
