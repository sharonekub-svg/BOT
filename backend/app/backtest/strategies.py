"""Backtest strategies.

A strategy sees one market's snapshot history (chronological) plus the final
outcome at the end, and decides entries. The engine handles fills, sizing,
and settlement at resolution.
"""

from dataclasses import dataclass
from typing import Protocol

from app.edge.engine import FairEstimate, MarketState, evaluate_market


@dataclass
class BacktestSnapshot:
    ts: str            # iso
    yes_price: float
    best_bid: float | None
    best_ask: float | None
    liquidity: float
    volume_24h: float
    hours_to_resolution: float | None


@dataclass
class EntryDecision:
    enter: bool
    direction: str = "buy_yes"   # buy_yes | buy_no
    kelly: float = 0.0
    predicted_prob: float | None = None
    edge_score: float = 0.0


class Strategy(Protocol):
    name: str

    def decide(self, market_id: str, history: list[BacktestSnapshot]) -> EntryDecision: ...


class MeanReversionStrategy:
    """Fade sharp single-interval moves: large jumps partially revert.

    A deliberately simple, honest baseline that needs nothing but price data.
    """

    name = "mean_reversion"

    def __init__(self, jump_threshold: float = 0.08, lookback: int = 12) -> None:
        self.jump_threshold = jump_threshold
        self.lookback = lookback

    def decide(self, market_id: str, history: list[BacktestSnapshot]) -> EntryDecision:
        if len(history) < self.lookback + 1:
            return EntryDecision(False)
        window = history[-(self.lookback + 1):]
        jump = window[-1].yes_price - window[0].yes_price
        if abs(jump) < self.jump_threshold:
            return EntryDecision(False)
        # assume one-third of the jump reverts
        fair = window[-1].yes_price - jump / 3.0
        state = MarketState(
            market_id=market_id,
            implied_prob=window[-1].yes_price,
            best_bid=window[-1].best_bid,
            best_ask=window[-1].best_ask,
            liquidity=window[-1].liquidity,
            volume_24h=window[-1].volume_24h,
            hours_to_resolution=window[-1].hours_to_resolution,
        )
        result = evaluate_market(state, [FairEstimate("mean_reversion", fair, 0.5)])
        if result.direction == "none" or result.expected_value <= 0:
            return EntryDecision(False)
        return EntryDecision(
            enter=True,
            direction=result.direction,
            kelly=result.kelly_fraction,
            predicted_prob=result.fair_prob,
            edge_score=result.edge_score,
        )


class LongshotFadeStrategy:
    """Structural bias harvest: longshots (<10c) are systematically overpriced.

    Buys NO on cheap YES contracts near resolution — the classic favorite-
    longshot bias documented across prediction markets.
    """

    name = "longshot_fade"

    def __init__(self, max_yes_price: float = 0.10, max_days_to_end: float = 30.0) -> None:
        self.max_yes_price = max_yes_price
        self.max_days_to_end = max_days_to_end

    def decide(self, market_id: str, history: list[BacktestSnapshot]) -> EntryDecision:
        if not history:
            return EntryDecision(False)
        last = history[-1]
        if last.yes_price > self.max_yes_price or last.yes_price <= 0.01:
            return EntryDecision(False)
        if last.hours_to_resolution is None or last.hours_to_resolution > self.max_days_to_end * 24:
            return EntryDecision(False)
        fair = last.yes_price * 0.6  # assume longshots are ~40% overpriced
        return EntryDecision(
            enter=True,
            direction="buy_no",
            kelly=min(0.05, (last.yes_price - fair) / max(last.yes_price, 1e-9) * 0.1),
            predicted_prob=fair,
            edge_score=60.0,
        )


STRATEGIES: dict[str, type] = {
    MeanReversionStrategy.name: MeanReversionStrategy,
    LongshotFadeStrategy.name: LongshotFadeStrategy,
}
