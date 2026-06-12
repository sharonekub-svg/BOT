"""Edge detection engine.

Pure functions over market state: implied vs fair probability, expected value,
Kelly sizing, and a composite 0-100 Edge Score. No I/O — fully unit-testable.
"""

from dataclasses import dataclass, field

from app.core.utils import clamp

MIN_PRICE = 0.01
MAX_PRICE = 0.99


@dataclass
class FairEstimate:
    """One independent probability estimate (AI, ML model, momentum model...)."""

    source: str       # "ai" | "ml" | "momentum" | ...
    prob: float       # P(YES)
    confidence: float  # 0..1, weights the estimate in the ensemble


@dataclass
class MarketState:
    """Inputs the edge engine needs about one market at one moment."""

    market_id: str
    implied_prob: float                 # current YES mid/last price
    best_bid: float | None = None       # YES bid
    best_ask: float | None = None       # YES ask
    liquidity: float = 0.0
    volume_24h: float = 0.0
    hours_to_resolution: float | None = None
    anomaly_severity: float = 0.0       # 0..1 from the anomaly detector
    category: str | None = None


@dataclass
class EdgeResult:
    market_id: str
    direction: str            # buy_yes | buy_no | none
    edge_score: float         # 0..100
    implied_prob: float
    fair_prob: float
    confidence: float
    entry_price: float | None
    expected_value: float     # ROI per $1 at the executable price
    kelly_fraction: float     # full Kelly fraction of bankroll (pre fractional cap)
    components: dict = field(default_factory=dict)


def combine_fair_estimates(implied: float, estimates: list[FairEstimate]) -> tuple[float, float]:
    """Confidence-weighted ensemble of fair-probability estimates.

    The market's implied probability anchors the ensemble (markets are mostly
    right); independent estimates pull it away in proportion to confidence.
    Returns (fair_prob, ensemble_confidence).
    """
    implied = clamp(implied, MIN_PRICE, MAX_PRICE)
    valid = [e for e in estimates if 0.0 < e.prob < 1.0 and e.confidence > 0]
    if not valid:
        return implied, 0.0

    anchor_weight = 1.0  # the market itself
    total_weight = anchor_weight + sum(e.confidence for e in valid)
    fair = (implied * anchor_weight + sum(e.prob * e.confidence for e in valid)) / total_weight

    # Agreement raises confidence: estimates pointing the same way reinforce.
    directions = [1 if e.prob > implied else -1 for e in valid]
    agreement = abs(sum(directions)) / len(directions)
    avg_conf = sum(e.confidence for e in valid) / len(valid)
    ensemble_confidence = clamp(avg_conf * (0.5 + 0.5 * agreement), 0.0, 1.0)
    return clamp(fair, MIN_PRICE, MAX_PRICE), ensemble_confidence


def expected_value(side_fair: float, side_price: float, fee_rate: float = 0.0) -> float:
    """ROI per $1 staked buying a side at `side_price` worth `side_fair`."""
    if side_price <= 0:
        return 0.0
    payout_per_share = 1.0 - fee_rate
    return (side_fair * payout_per_share - side_price) / side_price


def kelly_fraction(side_fair: float, side_price: float) -> float:
    """Full Kelly for a binary contract bought at `side_price`.

    Net odds b = (1-p)/p; f* = fair - (1-fair) * p / (1-p).
    """
    p = clamp(side_price, MIN_PRICE, MAX_PRICE)
    f = side_fair - (1.0 - side_fair) * p / (1.0 - p)
    return clamp(f, 0.0, 1.0)


def _liquidity_score(liquidity: float) -> float:
    """Log-scaled: $1k -> ~0.4, $10k -> ~0.7, $100k+ -> 1.0."""
    if liquidity <= 0:
        return 0.0
    import math

    return clamp((math.log10(liquidity) - 1.0) / 4.0, 0.0, 1.0)


def _time_score(hours: float | None) -> float:
    """Sweet spot: resolution between ~1 day and ~60 days out.

    Too soon = little time for fair value to converge being wrong is costly;
    too far = capital locked and estimates noisy.
    """
    if hours is None:
        return 0.5
    days = hours / 24.0
    if days <= 0:
        return 0.0
    if days < 1:
        return 0.6
    if days <= 60:
        return 1.0
    if days <= 180:
        return 0.6
    return 0.3


def evaluate_market(
    state: MarketState,
    estimates: list[FairEstimate],
    fee_rate: float = 0.0,
    spread_buffer: float = 0.005,
) -> EdgeResult:
    """Produce direction, EV, Kelly and the 0-100 Edge Score for one market."""
    implied = clamp(state.implied_prob, MIN_PRICE, MAX_PRICE)
    fair, confidence = combine_fair_estimates(implied, estimates)

    # Executable prices: buy YES at the ask; buy NO at (1 - bid) of YES.
    ask_yes = state.best_ask if state.best_ask is not None else implied + spread_buffer
    bid_yes = state.best_bid if state.best_bid is not None else implied - spread_buffer
    ask_yes = clamp(ask_yes, MIN_PRICE, MAX_PRICE)
    bid_yes = clamp(bid_yes, MIN_PRICE, MAX_PRICE)

    if fair > implied:
        direction, side_fair, side_price = "buy_yes", fair, ask_yes
    else:
        direction, side_fair, side_price = "buy_no", 1.0 - fair, clamp(1.0 - bid_yes, MIN_PRICE, MAX_PRICE)

    ev = expected_value(side_fair, side_price, fee_rate)
    kelly = kelly_fraction(side_fair, side_price)

    mispricing = abs(fair - implied)
    components = {
        "mispricing": clamp(mispricing / 0.15, 0.0, 1.0),       # 15pp mispricing saturates
        "value": clamp(max(ev, 0.0) / 0.30, 0.0, 1.0),          # 30% ROI saturates
        "confidence": confidence,
        "liquidity": _liquidity_score(state.liquidity),
        "time": _time_score(state.hours_to_resolution),
        "anomaly": clamp(state.anomaly_severity, 0.0, 1.0),
    }
    weights = {
        "mispricing": 0.28,
        "value": 0.20,
        "confidence": 0.24,
        "liquidity": 0.14,
        "time": 0.08,
        "anomaly": 0.06,
    }
    score = 100.0 * sum(components[k] * weights[k] for k in weights)

    # No edge without either a real mispricing or an anomaly to trade.
    if ev <= 0 and components["anomaly"] < 0.5:
        score = min(score, 25.0)
        direction = "none" if mispricing < 0.005 else direction

    return EdgeResult(
        market_id=state.market_id,
        direction=direction,
        edge_score=round(clamp(score, 0.0, 100.0), 2),
        implied_prob=round(implied, 4),
        fair_prob=round(fair, 4),
        confidence=round(confidence, 4),
        entry_price=round(side_price, 4),
        expected_value=round(ev, 4),
        kelly_fraction=round(kelly, 4),
        components={k: round(v, 4) for k, v in components.items()},
    )
