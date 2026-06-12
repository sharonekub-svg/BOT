"""Risk manager — every order passes through here before execution.

Enforces (all configurable):
- max risk per trade (% of equity) via fractional-Kelly sizing caps
- per-market / per-category / total exposure limits
- max open positions
- daily loss limit  -> trading halted for the day
- max drawdown      -> circuit breaker, trading halted until manual reset
- minimum liquidity and edge score for entries
"""

from dataclasses import dataclass, field

from app.config import get_settings
from app.core.utils import clamp
from app.logging_config import get_logger
from app.risk.sizing import SizingInputs, SizingResult, size_position

log = get_logger(__name__)


@dataclass
class PortfolioState:
    equity: float
    cash: float
    total_exposure: float
    exposure_by_market: dict[str, float] = field(default_factory=dict)
    exposure_by_category: dict[str, float] = field(default_factory=dict)
    open_positions: int = 0
    daily_pnl: float = 0.0
    peak_equity: float = 0.0

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return clamp(1.0 - self.equity / self.peak_equity, 0.0, 1.0)


@dataclass
class TradeIntent:
    market_id: str
    category: str | None
    direction: str        # buy_yes | buy_no
    entry_price: float
    kelly: float
    edge_score: float
    liquidity: float


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    notional: float = 0.0
    shares: float = 0.0
    capped_by: str = ""


class RiskManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.circuit_breaker_tripped = False

    # ------------------------------------------------------------ checks

    def check_portfolio_health(self, state: PortfolioState) -> list[str]:
        """Returns active risk warnings; trips the circuit breaker on max DD."""
        warnings: list[str] = []
        s = self.settings

        if state.equity > 0 and state.daily_pnl < 0:
            daily_loss_pct = abs(state.daily_pnl) / state.equity * 100
            if daily_loss_pct >= s.max_daily_loss_pct:
                warnings.append(
                    f"daily loss limit hit ({daily_loss_pct:.1f}% >= {s.max_daily_loss_pct}%)"
                )

        if state.drawdown * 100 >= s.max_drawdown_pct:
            if not self.circuit_breaker_tripped:
                log.error("CIRCUIT BREAKER: drawdown %.1f%% >= %.1f%%",
                          state.drawdown * 100, s.max_drawdown_pct)
            self.circuit_breaker_tripped = True
            warnings.append(
                f"max drawdown breached ({state.drawdown * 100:.1f}% >= {s.max_drawdown_pct}%) — trading halted"
            )

        if state.equity > 0 and state.total_exposure / state.equity * 100 > s.max_total_exposure_pct:
            warnings.append("total exposure above limit")
        return warnings

    def reset_circuit_breaker(self) -> None:
        self.circuit_breaker_tripped = False
        log.warning("circuit breaker manually reset")

    def _daily_loss_exceeded(self, state: PortfolioState) -> bool:
        if state.equity <= 0 or state.daily_pnl >= 0:
            return False
        return abs(state.daily_pnl) / state.equity * 100 >= self.settings.max_daily_loss_pct

    # ------------------------------------------------------------ trade gate

    def evaluate_trade(self, state: PortfolioState, intent: TradeIntent) -> RiskDecision:
        s = self.settings

        if self.circuit_breaker_tripped:
            return RiskDecision(False, "circuit breaker tripped (max drawdown)")
        if self._daily_loss_exceeded(state):
            return RiskDecision(False, "daily loss limit reached")
        if intent.edge_score < s.min_edge_score_to_trade:
            return RiskDecision(
                False, f"edge score {intent.edge_score:.0f} below minimum {s.min_edge_score_to_trade:.0f}"
            )
        if intent.liquidity < s.min_liquidity_to_trade:
            return RiskDecision(False, f"liquidity {intent.liquidity:.0f} below minimum")
        if state.open_positions >= s.max_open_positions:
            return RiskDecision(False, "max open positions reached")
        if not (0.0 < intent.entry_price < 1.0):
            return RiskDecision(False, "entry price out of range")

        sizing: SizingResult = size_position(
            SizingInputs(
                bankroll=state.equity,
                kelly=intent.kelly,
                kelly_multiplier=s.kelly_fraction,
                max_risk_pct=s.max_risk_per_trade_pct,
                entry_price=intent.entry_price,
                liquidity=intent.liquidity,
            )
        )
        if sizing.notional <= 0:
            return RiskDecision(False, "sized to zero (kelly/limits)")

        notional = sizing.notional

        market_room = state.equity * s.max_market_exposure_pct / 100.0 - state.exposure_by_market.get(
            intent.market_id, 0.0
        )
        if market_room <= 0:
            return RiskDecision(False, "market exposure limit reached")
        notional = min(notional, market_room)

        if intent.category:
            category_room = (
                state.equity * s.max_category_exposure_pct / 100.0
                - state.exposure_by_category.get(intent.category, 0.0)
            )
            if category_room <= 0:
                return RiskDecision(False, "category exposure limit reached")
            notional = min(notional, category_room)

        total_room = state.equity * s.max_total_exposure_pct / 100.0 - state.total_exposure
        if total_room <= 0:
            return RiskDecision(False, "total exposure limit reached")
        notional = min(notional, total_room)

        if notional > state.cash:
            notional = state.cash
        if notional < 1.0:
            return RiskDecision(False, "insufficient cash/room after caps")

        return RiskDecision(
            approved=True,
            reason="ok",
            notional=round(notional, 2),
            shares=round(notional / intent.entry_price, 2),
            capped_by=sizing.capped_by,
        )

    # ------------------------------------------------------------ stops

    def stop_loss_hit(self, avg_price: float, current_price: float) -> bool:
        """Stop when the position has lost more than stop_loss_pct of entry value."""
        if avg_price <= 0 or current_price is None:
            return False
        loss_pct = (avg_price - current_price) / avg_price * 100
        return loss_pct >= self.settings.stop_loss_pct

    def hedge_trigger_hit(self, avg_price: float, current_price: float) -> bool:
        if avg_price <= 0 or current_price is None:
            return False
        loss_pct = (avg_price - current_price) / avg_price * 100
        return loss_pct >= self.settings.hedge_trigger_loss_pct
