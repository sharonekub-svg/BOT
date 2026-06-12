"""Position sizing: fractional Kelly with hard caps."""

from dataclasses import dataclass

from app.core.utils import clamp


@dataclass
class SizingInputs:
    bankroll: float          # current equity
    kelly: float             # full Kelly fraction from the edge engine
    kelly_multiplier: float  # e.g. 0.25 = quarter Kelly
    max_risk_pct: float      # hard cap, % of bankroll per trade
    entry_price: float       # cost per share
    liquidity: float         # market liquidity (caps participation)
    max_liquidity_participation: float = 0.05  # never take >5% of pool


@dataclass
class SizingResult:
    notional: float   # dollars at stake
    shares: float
    capped_by: str    # kelly | max_risk | liquidity | zero


def size_position(inputs: SizingInputs) -> SizingResult:
    if inputs.bankroll <= 0 or inputs.entry_price <= 0 or inputs.kelly <= 0:
        return SizingResult(0.0, 0.0, "zero")

    kelly_notional = inputs.bankroll * clamp(inputs.kelly * inputs.kelly_multiplier, 0.0, 1.0)
    risk_cap = inputs.bankroll * inputs.max_risk_pct / 100.0
    liquidity_cap = max(inputs.liquidity, 0.0) * inputs.max_liquidity_participation

    notional = kelly_notional
    capped_by = "kelly"
    if risk_cap < notional:
        notional, capped_by = risk_cap, "max_risk"
    if liquidity_cap < notional:
        notional, capped_by = liquidity_cap, "liquidity"

    if notional < 1.0:  # ignore dust
        return SizingResult(0.0, 0.0, "zero")
    return SizingResult(round(notional, 2), round(notional / inputs.entry_price, 2), capped_by)
