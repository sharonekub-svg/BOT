"""Execution engine.

Owns the trade lifecycle: signal -> risk gate -> broker -> position/portfolio
accounting. Also runs stop-losses, auto-hedging, and portfolio snapshots.

Position accounting (one Position row per market+outcome):
- buys raise qty and re-average price; sells realize PnL against avg price
- mark-to-market uses the YES price (NO marks at 1 - yes_price)
"""

from datetime import datetime, time, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.events import get_event_bus
from app.core.utils import now_utc
from app.db import repositories as repo
from app.db.base import session_scope
from app.db.models import Market, PortfolioSnapshot, Position, Signal, Trade
from app.execution.broker import Broker, OrderRequest, PaperBroker
from app.logging_config import get_logger
from app.risk.manager import PortfolioState, RiskManager, TradeIntent

log = get_logger(__name__)


def mark_price(outcome: str, yes_price: float | None) -> float | None:
    if yes_price is None:
        return None
    return yes_price if outcome == "YES" else 1.0 - yes_price


class ExecutionEngine:
    def __init__(self, broker: Broker | None = None, risk: RiskManager | None = None) -> None:
        self.settings = get_settings()
        self.risk = risk or RiskManager()
        if broker is not None:
            self.broker = broker
        elif self.settings.trading_mode == "live":
            from app.execution.polymarket_broker import PolymarketBroker

            self.broker = PolymarketBroker()
        else:
            self.broker = PaperBroker()

    # ------------------------------------------------------- portfolio state

    async def portfolio_state(self, session: AsyncSession) -> PortfolioState:
        positions = await repo.open_positions(session)
        exposure_by_market: dict[str, float] = {}
        exposure_by_category: dict[str, float] = {}
        unrealized = 0.0
        exposure = 0.0

        for pos in positions:
            market = await repo.get_market(session, pos.market_id)
            current = mark_price(pos.outcome, market.yes_price if market else None)
            value = (current if current is not None else pos.avg_price) * pos.qty
            cost = pos.avg_price * pos.qty
            exposure += value
            unrealized += value - cost
            exposure_by_market[pos.market_id] = exposure_by_market.get(pos.market_id, 0.0) + value
            category = (market.category if market else None) or "other"
            exposure_by_category[category] = exposure_by_category.get(category, 0.0) + value

        last = await repo.latest_portfolio(session)
        starting = self.settings.starting_bankroll
        cash = last.cash if last else starting
        peak = max(last.peak_equity if last else starting, starting)

        day_start = datetime.combine(now_utc().date(), time.min, tzinfo=timezone.utc)
        realized_today = await repo.realized_pnl_between(session, day_start, now_utc())

        equity = cash + exposure
        return PortfolioState(
            equity=equity,
            cash=cash,
            total_exposure=exposure,
            exposure_by_market=exposure_by_market,
            exposure_by_category=exposure_by_category,
            open_positions=len(positions),
            daily_pnl=realized_today + unrealized,
            peak_equity=max(peak, equity),
        )

    async def snapshot_portfolio(self) -> PortfolioSnapshot:
        async with session_scope() as session:
            state = await self.portfolio_state(session)
            positions = await repo.open_positions(session)
            unrealized = 0.0
            for pos in positions:
                market = await repo.get_market(session, pos.market_id)
                current = mark_price(pos.outcome, market.yes_price if market else None)
                if current is not None:
                    unrealized += (current - pos.avg_price) * pos.qty
            snap = PortfolioSnapshot(
                ts=now_utc(),
                equity=round(state.equity, 2),
                cash=round(state.cash, 2),
                exposure=round(state.total_exposure, 2),
                unrealized_pnl=round(unrealized, 2),
                realized_pnl_today=round(state.daily_pnl - unrealized, 2),
                peak_equity=round(state.peak_equity, 2),
                drawdown=round(state.drawdown, 4),
                open_positions=state.open_positions,
            )
            session.add(snap)
        return snap

    # ------------------------------------------------------- entries

    async def execute_signal(self, signal: Signal, market: Market) -> Trade | None:
        """Risk-gate and execute one signal. Returns the trade or None."""
        async with session_scope() as session:
            state = await self.portfolio_state(session)
            intent = TradeIntent(
                market_id=market.id,
                category=market.category,
                direction=signal.direction,
                entry_price=self._entry_price(signal.direction, market),
                kelly=signal.kelly_size or 0.0,
                edge_score=signal.edge_score,
                liquidity=market.liquidity or 0.0,
            )
            decision = self.risk.evaluate_trade(state, intent)
            if not decision.approved:
                log.info("signal %s rejected: %s", signal.id, decision.reason)
                return None
            return await self._place_and_book(
                session,
                market=market,
                outcome="YES" if signal.direction == "buy_yes" else "NO",
                side="buy",
                qty=decision.shares,
                order_type="market",
                signal_id=signal.id,
                reason="entry",
            )

    def _entry_price(self, direction: str, market: Market) -> float:
        if direction == "buy_yes":
            return market.best_ask or market.yes_price or 0.5
        bid = market.best_bid if market.best_bid is not None else market.yes_price or 0.5
        return max(0.01, min(0.99, 1.0 - bid))

    # ------------------------------------------------------- manual + close

    async def manual_trade(
        self,
        market_id: str,
        outcome: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> Trade | None:
        async with session_scope() as session:
            market = await repo.get_market(session, market_id)
            if market is None:
                raise ValueError(f"unknown market {market_id}")
            return await self._place_and_book(
                session,
                market=market,
                outcome=outcome.upper(),
                side=side,
                qty=qty,
                order_type=order_type,
                limit_price=limit_price,
                reason="manual",
            )

    async def close_position(self, position_id: int, reason: str = "close") -> Trade | None:
        async with session_scope() as session:
            position = await session.get(Position, position_id)
            if position is None or position.status != "open":
                return None
            market = await repo.get_market(session, position.market_id)
            if market is None:
                return None
            return await self._place_and_book(
                session,
                market=market,
                outcome=position.outcome,
                side="sell",
                qty=position.qty,
                order_type="market",
                reason=reason,
            )

    # ------------------------------------------------------- stops & hedging

    async def run_protections(self) -> dict:
        """Stop-losses and auto-hedges across open positions. Returns counts."""
        stops = hedges = 0
        async with session_scope() as session:
            positions = await repo.open_positions(session)
            for pos in positions:
                market = await repo.get_market(session, pos.market_id)
                if market is None:
                    continue
                current = mark_price(pos.outcome, market.yes_price)
                if current is None:
                    continue
                if self.risk.stop_loss_hit(pos.avg_price, current):
                    await self._place_and_book(
                        session, market=market, outcome=pos.outcome, side="sell",
                        qty=pos.qty, order_type="market", reason="stop_loss",
                    )
                    stops += 1
                    continue
                if self.settings.auto_hedge_enabled and self.risk.hedge_trigger_hit(pos.avg_price, current):
                    opposite = "NO" if pos.outcome == "YES" else "YES"
                    already = await repo.position_for(session, pos.market_id, opposite)
                    if already is None:
                        # Hedge half the position on the other side to cap the loss range.
                        await self._place_and_book(
                            session, market=market, outcome=opposite, side="buy",
                            qty=round(pos.qty / 2, 2), order_type="market", reason="hedge",
                        )
                        hedges += 1
        if stops or hedges:
            await get_event_bus().publish("protections", {"stop_losses": stops, "hedges": hedges})
        return {"stop_losses": stops, "hedges": hedges}

    async def rebalance(self, max_orders: int = 5) -> int:
        """Trim positions whose share of exposure exceeds the per-market cap."""
        placed = 0
        async with session_scope() as session:
            state = await self.portfolio_state(session)
            if state.equity <= 0:
                return 0
            cap = state.equity * self.settings.max_market_exposure_pct / 100.0
            for market_id, value in sorted(
                state.exposure_by_market.items(), key=lambda kv: kv[1], reverse=True
            ):
                if placed >= max_orders or value <= cap * 1.1:
                    continue
                market = await repo.get_market(session, market_id)
                positions = [p for p in await repo.open_positions(session) if p.market_id == market_id]
                for pos in positions:
                    current = mark_price(pos.outcome, market.yes_price if market else None)
                    if not current:
                        continue
                    excess_value = value - cap
                    trim_qty = round(min(pos.qty, excess_value / current), 2)
                    if trim_qty >= 1:
                        await self._place_and_book(
                            session, market=market, outcome=pos.outcome, side="sell",
                            qty=trim_qty, order_type="market", reason="rebalance",
                        )
                        placed += 1
                        break
        return placed

    # ------------------------------------------------------- internals

    async def _place_and_book(
        self,
        session: AsyncSession,
        market: Market,
        outcome: str,
        side: str,
        qty: float,
        order_type: str,
        limit_price: float | None = None,
        signal_id: int | None = None,
        reason: str = "entry",
    ) -> Trade | None:
        if qty <= 0:
            return None
        token_ids = market.clob_token_ids or []
        token_id = None
        if token_ids:
            token_id = token_ids[0] if outcome == "YES" else (token_ids[1] if len(token_ids) > 1 else None)

        yes_bid, yes_ask = market.best_bid, market.best_ask
        if outcome == "YES":
            bid, ask = yes_bid, yes_ask
        else:  # NO quotes derive from YES book
            bid = 1.0 - yes_ask if yes_ask is not None else None
            ask = 1.0 - yes_bid if yes_bid is not None else None

        result = await self.broker.place_order(
            OrderRequest(
                market_id=market.id,
                token_id=token_id,
                outcome=outcome,
                side=side,
                order_type=order_type,
                qty=qty,
                limit_price=limit_price,
                current_bid=bid,
                current_ask=ask,
            )
        )

        trade = Trade(
            market_id=market.id,
            signal_id=signal_id,
            mode=self.settings.trading_mode,
            side=side,
            outcome=outcome,
            order_type=order_type,
            qty=qty,
            limit_price=limit_price,
            fill_price=result.fill_price,
            notional=round((result.fill_price or limit_price or 0.0) * qty, 2),
            fee=round((result.fill_price or 0.0) * qty * self.settings.fee_rate, 4),
            status=result.status,
            order_id=result.order_id,
            reason=reason,
            created_at=now_utc(),
            filled_at=now_utc() if result.status == "filled" else None,
        )
        session.add(trade)

        if result.status == "filled" and result.fill_price is not None:
            await self._apply_fill(session, market.id, outcome, side, result.filled_qty or qty,
                                   result.fill_price, trade.fee)
            await get_event_bus().publish(
                "trade",
                {
                    "market_id": market.id, "question": market.question[:80], "side": side,
                    "outcome": outcome, "qty": qty, "price": result.fill_price, "reason": reason,
                },
            )
        return trade

    async def _apply_fill(
        self,
        session: AsyncSession,
        market_id: str,
        outcome: str,
        side: str,
        qty: float,
        price: float,
        fee: float,
    ) -> None:
        position = await repo.position_for(session, market_id, outcome)
        cash_delta = -(qty * price + fee) if side == "buy" else qty * price - fee

        if side == "buy":
            if position is None:
                session.add(
                    Position(
                        market_id=market_id, outcome=outcome, qty=qty, avg_price=price,
                        opened_at=now_utc(), status="open",
                    )
                )
            else:
                total_cost = position.avg_price * position.qty + price * qty
                position.qty = round(position.qty + qty, 4)
                position.avg_price = round(total_cost / position.qty, 4)
        else:  # sell
            if position is None:
                log.warning("sell without open position on %s %s", market_id, outcome)
            else:
                sell_qty = min(qty, position.qty)
                position.realized_pnl = round(
                    position.realized_pnl + (price - position.avg_price) * sell_qty - fee, 4
                )
                position.qty = round(position.qty - sell_qty, 4)
                if position.qty <= 0.0001:
                    position.qty = 0.0
                    position.status = "closed"
                    position.closed_at = now_utc()

        last = await repo.latest_portfolio(session)
        cash = (last.cash if last else self.settings.starting_bankroll) + cash_delta
        # Cash moves immediately; full snapshot (equity/drawdown) is written by the risk loop.
        state = await self.portfolio_state(session)
        session.add(
            PortfolioSnapshot(
                ts=now_utc(),
                equity=round(cash + state.total_exposure, 2),
                cash=round(cash, 2),
                exposure=round(state.total_exposure, 2),
                unrealized_pnl=0.0,
                realized_pnl_today=0.0,
                peak_equity=round(max(state.peak_equity, cash + state.total_exposure), 2),
                drawdown=round(state.drawdown, 4),
                open_positions=state.open_positions,
            )
        )
