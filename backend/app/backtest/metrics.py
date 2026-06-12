"""Backtest performance metrics — pure numpy, fully unit-tested."""

import numpy as np

TRADING_DAYS_PER_YEAR = 365  # prediction markets trade continuously


def daily_returns(equity_curve: list[float]) -> np.ndarray:
    arr = np.asarray(equity_curve, dtype=float)
    if arr.size < 2:
        return np.array([])
    prev = arr[:-1].copy()
    prev[prev == 0] = 1e-9
    return arr[1:] / prev - 1.0


def sharpe_ratio(equity_curve: list[float], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float | None:
    rets = daily_returns(equity_curve)
    if rets.size < 2 or np.std(rets) < 1e-12:
        return None
    return float(np.mean(rets) / np.std(rets) * np.sqrt(periods_per_year))


def sortino_ratio(equity_curve: list[float], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float | None:
    rets = daily_returns(equity_curve)
    if rets.size < 2:
        return None
    downside = rets[rets < 0]
    if downside.size == 0:
        return None
    dd_std = np.std(downside)
    if dd_std < 1e-12:
        return None
    return float(np.mean(rets) / dd_std * np.sqrt(periods_per_year))


def max_drawdown(equity_curve: list[float]) -> float:
    """Largest peak-to-trough loss as a fraction (0.2 = -20%)."""
    arr = np.asarray(equity_curve, dtype=float)
    if arr.size < 2:
        return 0.0
    peaks = np.maximum.accumulate(arr)
    peaks[peaks == 0] = 1e-9
    drawdowns = 1.0 - arr / peaks
    return float(np.max(drawdowns))


def cagr(equity_curve: list[float], n_days: float) -> float | None:
    if len(equity_curve) < 2 or n_days <= 0 or equity_curve[0] <= 0:
        return None
    total = equity_curve[-1] / equity_curve[0]
    if total <= 0:
        return None
    years = n_days / 365.0
    if years <= 0:
        return None
    return float(total ** (1.0 / years) - 1.0)


def win_rate(trade_pnls: list[float]) -> float | None:
    closed = [p for p in trade_pnls if p is not None]
    if not closed:
        return None
    wins = sum(1 for p in closed if p > 0)
    return wins / len(closed)


def profit_factor(trade_pnls: list[float]) -> float | None:
    gains = sum(p for p in trade_pnls if p and p > 0)
    losses = -sum(p for p in trade_pnls if p and p < 0)
    if losses <= 0:
        return None
    return float(gains / losses)


def ev_accuracy(predicted_probs: list[float], outcomes: list[int]) -> dict:
    """How good were our fair-value estimates? Brier + hit rate vs coin flip."""
    pairs = [(p, o) for p, o in zip(predicted_probs, outcomes) if p is not None and o is not None]
    if not pairs:
        return {"brier": None, "directional_hit_rate": None, "n": 0}
    p_arr = np.array([p for p, _ in pairs], dtype=float)
    o_arr = np.array([o for _, o in pairs], dtype=float)
    brier = float(np.mean((p_arr - o_arr) ** 2))
    hits = float(np.mean(((p_arr > 0.5) & (o_arr == 1)) | ((p_arr <= 0.5) & (o_arr == 0))))
    return {"brier": round(brier, 4), "directional_hit_rate": round(hits, 4), "n": len(pairs)}


def summarize(
    equity_curve: list[float],
    n_days: float,
    trade_pnls: list[float],
    predicted_probs: list[float] | None = None,
    outcomes: list[int] | None = None,
) -> dict:
    summary = {
        "final_equity": round(equity_curve[-1], 2) if equity_curve else None,
        "total_return": round(equity_curve[-1] / equity_curve[0] - 1.0, 4)
        if len(equity_curve) >= 2 and equity_curve[0] > 0
        else None,
        "sharpe": _round(sharpe_ratio(equity_curve)),
        "sortino": _round(sortino_ratio(equity_curve)),
        "max_drawdown": round(max_drawdown(equity_curve), 4),
        "cagr": _round(cagr(equity_curve, n_days)),
        "win_rate": _round(win_rate(trade_pnls)),
        "profit_factor": _round(profit_factor(trade_pnls)),
        "n_trades": len([p for p in trade_pnls if p is not None]),
    }
    if predicted_probs is not None and outcomes is not None:
        summary["ev_accuracy"] = ev_accuracy(predicted_probs, outcomes)
    return summary


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)
