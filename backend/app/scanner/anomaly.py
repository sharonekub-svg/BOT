"""Streaming anomaly detection over market snapshots.

Keeps a rolling window per market and flags:
- price_jump      — |Δprice| large vs rolling volatility (z-score)
- volume_spike    — 24h volume well above its rolling mean
- liquidity_drop  — liquidity collapses vs its rolling mean
"""

import statistics
from collections import deque
from dataclasses import dataclass

from app.core.utils import clamp


@dataclass
class Anomaly:
    market_id: str
    kind: str       # price_jump | volume_spike | liquidity_drop
    severity: float  # 0..1
    detail: dict


class RollingState:
    def __init__(self, maxlen: int = 96) -> None:
        self.prices: deque[float] = deque(maxlen=maxlen)
        self.volumes: deque[float] = deque(maxlen=maxlen)
        self.liquidity: deque[float] = deque(maxlen=maxlen)


class AnomalyDetector:
    def __init__(
        self,
        window: int = 96,
        min_observations: int = 8,
        price_z_threshold: float = 3.0,
        volume_ratio_threshold: float = 3.0,
        liquidity_drop_ratio: float = 0.5,
    ) -> None:
        self.window = window
        self.min_observations = min_observations
        self.price_z_threshold = price_z_threshold
        self.volume_ratio_threshold = volume_ratio_threshold
        self.liquidity_drop_ratio = liquidity_drop_ratio
        self._state: dict[str, RollingState] = {}

    def observe(
        self,
        market_id: str,
        price: float | None,
        volume_24h: float | None,
        liquidity: float | None,
    ) -> list[Anomaly]:
        state = self._state.setdefault(market_id, RollingState(self.window))
        anomalies: list[Anomaly] = []

        if price is not None:
            anomalies += self._check_price(market_id, state, price)
            state.prices.append(price)
        if volume_24h is not None:
            anomalies += self._check_volume(market_id, state, volume_24h)
            state.volumes.append(volume_24h)
        if liquidity is not None:
            anomalies += self._check_liquidity(market_id, state, liquidity)
            state.liquidity.append(liquidity)
        return anomalies

    # ---------------------------------------------------------- checks

    def _check_price(self, market_id: str, state: RollingState, price: float) -> list[Anomaly]:
        if len(state.prices) < self.min_observations:
            return []
        deltas = [b - a for a, b in zip(list(state.prices)[:-1], list(state.prices)[1:])]
        if len(deltas) < 2:
            return []
        sigma = statistics.pstdev(deltas)
        sigma = max(sigma, 0.002)  # floor so flat markets still need a real move
        delta = price - state.prices[-1]
        z = abs(delta) / sigma
        if z < self.price_z_threshold:
            return []
        severity = clamp((z - self.price_z_threshold) / self.price_z_threshold, 0.1, 1.0)
        return [
            Anomaly(
                market_id,
                "price_jump",
                round(severity, 3),
                {"delta": round(delta, 4), "z_score": round(z, 2), "from": state.prices[-1], "to": price},
            )
        ]

    def _check_volume(self, market_id: str, state: RollingState, volume: float) -> list[Anomaly]:
        if len(state.volumes) < self.min_observations:
            return []
        mean = statistics.fmean(state.volumes)
        if mean <= 0:
            return []
        ratio = volume / mean
        if ratio < self.volume_ratio_threshold:
            return []
        severity = clamp((ratio - self.volume_ratio_threshold) / (2 * self.volume_ratio_threshold), 0.1, 1.0)
        return [
            Anomaly(
                market_id,
                "volume_spike",
                round(severity, 3),
                {"volume": volume, "rolling_mean": round(mean, 2), "ratio": round(ratio, 2)},
            )
        ]

    def _check_liquidity(self, market_id: str, state: RollingState, liquidity: float) -> list[Anomaly]:
        if len(state.liquidity) < self.min_observations:
            return []
        mean = statistics.fmean(state.liquidity)
        if mean <= 0:
            return []
        ratio = liquidity / mean
        if ratio > self.liquidity_drop_ratio:
            return []
        severity = clamp(1.0 - ratio / self.liquidity_drop_ratio, 0.1, 1.0)
        return [
            Anomaly(
                market_id,
                "liquidity_drop",
                round(severity, 3),
                {"liquidity": liquidity, "rolling_mean": round(mean, 2), "ratio": round(ratio, 2)},
            )
        ]
