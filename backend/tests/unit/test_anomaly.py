from app.scanner.anomaly import AnomalyDetector


def warm_up(detector: AnomalyDetector, market_id: str, n: int = 20,
            price: float = 0.50, volume: float = 10_000, liquidity: float = 50_000):
    for i in range(n):
        # tiny noise so volatility is nonzero but small
        detector.observe(market_id, price + (i % 3 - 1) * 0.001, volume, liquidity)


class TestPriceJump:
    def test_jump_detected_after_warmup(self):
        detector = AnomalyDetector()
        warm_up(detector, "m1")
        anomalies = detector.observe("m1", 0.65, 10_000, 50_000)  # +15 point jump
        kinds = {a.kind for a in anomalies}
        assert "price_jump" in kinds
        jump = next(a for a in anomalies if a.kind == "price_jump")
        assert 0 < jump.severity <= 1
        assert jump.detail["z_score"] > 3

    def test_small_move_ignored(self):
        detector = AnomalyDetector()
        warm_up(detector, "m1")
        anomalies = detector.observe("m1", 0.502, 10_000, 50_000)
        assert all(a.kind != "price_jump" for a in anomalies)

    def test_no_detection_during_warmup(self):
        detector = AnomalyDetector(min_observations=8)
        for _ in range(5):
            assert detector.observe("m1", 0.5, 1_000, 10_000) == []
        # 6th observation with a big jump still inside warmup window
        assert detector.observe("m1", 0.9, 1_000, 10_000) == []


class TestVolumeSpike:
    def test_spike_detected(self):
        detector = AnomalyDetector()
        warm_up(detector, "m1", volume=10_000)
        anomalies = detector.observe("m1", 0.50, 50_000, 50_000)  # 5x volume
        assert any(a.kind == "volume_spike" for a in anomalies)

    def test_normal_volume_ignored(self):
        detector = AnomalyDetector()
        warm_up(detector, "m1", volume=10_000)
        anomalies = detector.observe("m1", 0.50, 12_000, 50_000)
        assert all(a.kind != "volume_spike" for a in anomalies)


class TestLiquidityDrop:
    def test_drop_detected(self):
        detector = AnomalyDetector()
        warm_up(detector, "m1", liquidity=50_000)
        anomalies = detector.observe("m1", 0.50, 10_000, 10_000)  # -80% liquidity
        assert any(a.kind == "liquidity_drop" for a in anomalies)

    def test_stable_liquidity_ignored(self):
        detector = AnomalyDetector()
        warm_up(detector, "m1", liquidity=50_000)
        anomalies = detector.observe("m1", 0.50, 10_000, 48_000)
        assert all(a.kind != "liquidity_drop" for a in anomalies)


class TestIsolation:
    def test_markets_tracked_independently(self):
        detector = AnomalyDetector()
        warm_up(detector, "m1")
        # m2 has no history -> jump on m2 must not fire
        assert detector.observe("m2", 0.9, 1_000, 1_000) == []
