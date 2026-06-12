"""Feature engineering from market snapshot windows."""

from dataclasses import dataclass

import numpy as np

FEATURE_NAMES = [
    "implied_prob",
    "momentum_short",   # price change over last quarter of the window
    "momentum_long",    # price change over the whole window
    "volatility",       # std of price diffs
    "spread",
    "log_liquidity",
    "log_volume",
    "volume_trend",     # last/mean ratio
    "days_to_end",
]


@dataclass
class FeatureRow:
    market_id: str
    features: list[float]
    label: int | None = None  # 1 = resolved YES


def build_features(
    prices: list[float],
    spreads: list[float],
    liquidity: list[float],
    volumes: list[float],
    days_to_end: float | None,
) -> list[float] | None:
    """Build one feature vector from a chronological snapshot window."""
    prices = [p for p in prices if p is not None]
    if len(prices) < 4:
        return None
    arr = np.asarray(prices, dtype=float)
    quarter = max(1, len(arr) // 4)

    implied = float(arr[-1])
    momentum_short = float(arr[-1] - arr[-quarter])
    momentum_long = float(arr[-1] - arr[0])
    volatility = float(np.std(np.diff(arr))) if len(arr) > 1 else 0.0

    spread = float(np.nanmean([s for s in spreads if s is not None])) if any(
        s is not None for s in spreads
    ) else 0.02
    liq = [v for v in liquidity if v]
    vol = [v for v in volumes if v]
    log_liquidity = float(np.log10(max(np.mean(liq), 1.0))) if liq else 0.0
    log_volume = float(np.log10(max(np.mean(vol), 1.0))) if vol else 0.0
    volume_trend = float(vol[-1] / max(np.mean(vol), 1e-9)) if vol else 1.0

    return [
        implied,
        momentum_short,
        momentum_long,
        volatility,
        spread,
        log_liquidity,
        log_volume,
        min(volume_trend, 10.0),
        min(days_to_end if days_to_end is not None else 30.0, 365.0),
    ]
