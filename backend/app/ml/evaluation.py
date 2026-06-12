"""Prediction evaluation: AI vs ML vs market vs final outcome."""

from dataclasses import dataclass

import numpy as np


@dataclass
class CalibrationReport:
    n: int
    brier_model: float | None
    brier_ai: float | None
    brier_market: float | None
    model_beats_market: bool | None
    ai_beats_market: bool | None
    buckets: list[dict]  # reliability diagram for market probs


def brier(probs: list[float], outcomes: list[int]) -> float | None:
    pairs = [(p, o) for p, o in zip(probs, outcomes) if p is not None and o is not None]
    if not pairs:
        return None
    arr_p = np.array([p for p, _ in pairs], dtype=float)
    arr_o = np.array([o for _, o in pairs], dtype=float)
    return float(np.mean((arr_p - arr_o) ** 2))


def reliability_buckets(probs: list[float], outcomes: list[int], n_buckets: int = 10) -> list[dict]:
    pairs = [(p, o) for p, o in zip(probs, outcomes) if p is not None and o is not None]
    buckets = []
    for i in range(n_buckets):
        lo, hi = i / n_buckets, (i + 1) / n_buckets
        inside = [(p, o) for p, o in pairs if lo <= p < hi or (i == n_buckets - 1 and p == hi)]
        if inside:
            buckets.append(
                {
                    "bucket": f"{lo:.1f}-{hi:.1f}",
                    "predicted": round(float(np.mean([p for p, _ in inside])), 4),
                    "actual": round(float(np.mean([o for _, o in inside])), 4),
                    "count": len(inside),
                }
            )
        else:
            buckets.append({"bucket": f"{lo:.1f}-{hi:.1f}", "predicted": None, "actual": None, "count": 0})
    return buckets


def evaluate_predictions(records: list[dict]) -> CalibrationReport:
    """`records`: [{model_prob, ai_prob, market_prob, outcome}] with outcome 0/1."""
    resolved = [r for r in records if r.get("outcome") is not None]
    outcomes = [int(r["outcome"]) for r in resolved]

    def col(key: str) -> list[float]:
        return [r.get(key) for r in resolved]

    b_model = brier(col("model_prob"), outcomes)
    b_ai = brier(col("ai_prob"), outcomes)
    b_market = brier(col("market_prob"), outcomes)

    return CalibrationReport(
        n=len(resolved),
        brier_model=b_model,
        brier_ai=b_ai,
        brier_market=b_market,
        model_beats_market=(b_model < b_market) if (b_model is not None and b_market is not None) else None,
        ai_beats_market=(b_ai < b_market) if (b_ai is not None and b_market is not None) else None,
        buckets=reliability_buckets(col("market_prob"), outcomes),
    )
