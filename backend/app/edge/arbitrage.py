"""Arbitrage detection.

Three families:
1. Binary complement — YES ask + NO ask < $1 (buy both, guaranteed $1 payout).
2. Multi-outcome     — within a mutually-exclusive event, sum of YES asks < $1
   (long basket) or sum of YES bids > $1 (short via NO side).
3. Cross-market      — implication violations between logically linked markets
   (if A implies B, P(A) must be <= P(B)).

All functions are pure and unit-tested; the worker persists the results.
"""

from dataclasses import dataclass, field


@dataclass
class ArbLeg:
    market_id: str
    question: str
    outcome: str   # YES | NO
    side: str      # buy | sell
    price: float


@dataclass
class ArbOpportunity:
    kind: str
    market_ids: list[str]
    legs: list[ArbLeg]
    gross_edge: float   # profit per $1 basket before fees
    net_edge: float     # after fees + execution buffer
    size_cap: float | None = None
    description: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "market_ids": self.market_ids,
            "legs": [vars(leg) for leg in self.legs],
            "gross_edge": round(self.gross_edge, 5),
            "net_edge": round(self.net_edge, 5),
            "size_cap": self.size_cap,
            "description": self.description,
        }


def binary_complement_arb(
    market_id: str,
    question: str,
    ask_yes: float | None,
    ask_no: float | None,
    fee_rate: float = 0.0,
    buffer: float = 0.005,
    depth_cap: float | None = None,
) -> ArbOpportunity | None:
    """Buy YES + NO when their combined cost is below the $1 settlement."""
    if ask_yes is None or ask_no is None or ask_yes <= 0 or ask_no <= 0:
        return None
    cost = ask_yes + ask_no
    gross = 1.0 - cost
    net = gross - fee_rate - buffer
    if net <= 0:
        return None
    return ArbOpportunity(
        kind="binary_complement",
        market_ids=[market_id],
        legs=[
            ArbLeg(market_id, question, "YES", "buy", ask_yes),
            ArbLeg(market_id, question, "NO", "buy", ask_no),
        ],
        gross_edge=gross,
        net_edge=net,
        size_cap=depth_cap,
        description=f"YES {ask_yes:.3f} + NO {ask_no:.3f} = {cost:.3f} < 1.00",
    )


def multi_outcome_arb(
    event_id: str,
    outcomes: list[dict],
    fee_rate: float = 0.0,
    buffer: float = 0.005,
) -> list[ArbOpportunity]:
    """Mutually-exclusive event arbitrage.

    `outcomes`: [{market_id, question, ask, bid}] — one entry per outcome
    market of the event (e.g. each candidate in an election).
    """
    results: list[ArbOpportunity] = []
    priced = [o for o in outcomes if o.get("ask") and o.get("bid")]
    if len(priced) < 2:
        return results

    # Long basket: buy YES on every outcome; exactly one pays $1.
    total_ask = sum(o["ask"] for o in priced)
    gross_long = 1.0 - total_ask
    net_long = gross_long - fee_rate * len(priced) - buffer
    if net_long > 0:
        results.append(
            ArbOpportunity(
                kind="multi_outcome_long",
                market_ids=[o["market_id"] for o in priced],
                legs=[ArbLeg(o["market_id"], o["question"], "YES", "buy", o["ask"]) for o in priced],
                gross_edge=gross_long,
                net_edge=net_long,
                description=f"event {event_id}: sum of YES asks {total_ask:.3f} < 1.00",
            )
        )

    # Short basket: when YES bids sum above $1, buying every NO costs
    # n - sum(bid) and pays n - 1 (all but one NO settle at $1).
    total_bid = sum(o["bid"] for o in priced)
    gross_short = total_bid - 1.0
    net_short = gross_short - fee_rate * len(priced) - buffer
    if net_short > 0:
        results.append(
            ArbOpportunity(
                kind="multi_outcome_short",
                market_ids=[o["market_id"] for o in priced],
                legs=[
                    ArbLeg(o["market_id"], o["question"], "NO", "buy", 1.0 - o["bid"]) for o in priced
                ],
                gross_edge=gross_short,
                net_edge=net_short,
                description=f"event {event_id}: sum of YES bids {total_bid:.3f} > 1.00",
            )
        )
    return results


def implication_violation(
    narrow: dict,
    broad: dict,
    min_gap: float = 0.02,
    fee_rate: float = 0.0,
) -> ArbOpportunity | None:
    """If `narrow` implies `broad` (A ⊆ B), then P(A) <= P(B) must hold.

    A violation (narrow priced above broad) is traded by buying NO on the
    narrow market and YES on the broad one.

    Each dict: {market_id, question, bid, ask}.
    """
    if not all(k in narrow and narrow[k] is not None for k in ("bid", "ask")):
        return None
    if not all(k in broad and broad[k] is not None for k in ("bid", "ask")):
        return None

    gap = narrow["bid"] - broad["ask"]  # executable: sell narrow, buy broad
    if gap < min_gap:
        return None
    cost_no_narrow = 1.0 - narrow["bid"]
    cost_yes_broad = broad["ask"]
    gross = gap
    net = gross - 2 * fee_rate
    if net <= 0:
        return None
    return ArbOpportunity(
        kind="cross_market",
        market_ids=[narrow["market_id"], broad["market_id"]],
        legs=[
            ArbLeg(narrow["market_id"], narrow["question"], "NO", "buy", cost_no_narrow),
            ArbLeg(broad["market_id"], broad["question"], "YES", "buy", cost_yes_broad),
        ],
        gross_edge=gross,
        net_edge=net,
        description=(
            f"implication violated: P({narrow['question'][:40]}…)={narrow['bid']:.2f} "
            f"> P({broad['question'][:40]}…)={broad['ask']:.2f}"
        ),
    )


@dataclass
class EventGroup:
    event_id: str
    markets: list[dict] = field(default_factory=list)


def group_event_outcomes(markets: list[dict]) -> list[EventGroup]:
    """Group neg-risk markets by event for multi-outcome scanning.

    `markets`: [{market_id, question, event_id, neg_risk, ask, bid}].
    """
    groups: dict[str, EventGroup] = {}
    for market in markets:
        event_id = market.get("event_id")
        if not event_id or not market.get("neg_risk"):
            continue
        groups.setdefault(event_id, EventGroup(event_id)).markets.append(market)
    return [g for g in groups.values() if len(g.markets) >= 2]
