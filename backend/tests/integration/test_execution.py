"""Execution engine integration tests (paper broker, in-memory DB)."""

from datetime import timedelta

import pytest

from app.core.utils import now_utc
from app.db.base import get_sessionmaker
from app.db.models import Market, Position
from app.execution.engine import ExecutionEngine


async def seed_market(yes_price=0.50, best_bid=0.49, best_ask=0.51, market_id="0xexec1"):
    async with get_sessionmaker()() as session:
        session.add(
            Market(
                id=market_id,
                question="Execution test market?",
                category="tech",
                outcomes=["Yes", "No"],
                end_date=now_utc() + timedelta(days=5),
                active=True,
                closed=False,
                yes_price=yes_price,
                best_bid=best_bid,
                best_ask=best_ask,
                spread=best_ask - best_bid,
                liquidity=50_000,
                volume_24h=10_000,
            )
        )
        await session.commit()


async def set_market_price(market_id: str, yes_price: float, best_bid: float, best_ask: float):
    async with get_sessionmaker()() as session:
        market = await session.get(Market, market_id)
        market.yes_price = yes_price
        market.best_bid = best_bid
        market.best_ask = best_ask
        await session.commit()


@pytest.fixture
def engine(db):
    return ExecutionEngine()


class TestPaperTrading:
    async def test_buy_creates_position_and_moves_cash(self, db, engine):
        await seed_market()
        trade = await engine.manual_trade("0xexec1", "YES", "buy", qty=100)
        assert trade.status == "filled"
        assert 0.50 < trade.fill_price < 0.55  # ask + slippage

        async with get_sessionmaker()() as session:
            state = await engine.portfolio_state(session)
        assert state.open_positions == 1
        assert state.cash < 10_000
        assert state.total_exposure > 0

    async def test_buy_then_sell_realizes_pnl(self, db, engine):
        await seed_market()
        await engine.manual_trade("0xexec1", "YES", "buy", qty=100)
        sell = await engine.manual_trade("0xexec1", "YES", "sell", qty=100)
        assert sell.status == "filled"

        async with get_sessionmaker()() as session:
            from sqlalchemy import select

            rows = await session.execute(select(Position))
            position = rows.scalars().first()
        assert position.status == "closed"
        # bought at ask+slippage, sold at bid-slippage -> small loss from spread
        assert position.realized_pnl < 0

    async def test_averaging_up(self, db, engine):
        await seed_market()
        await engine.manual_trade("0xexec1", "YES", "buy", qty=100)
        await set_market_price("0xexec1", 0.60, 0.59, 0.61)
        await engine.manual_trade("0xexec1", "YES", "buy", qty=100)

        async with get_sessionmaker()() as session:
            from sqlalchemy import select

            rows = await session.execute(select(Position).where(Position.status == "open"))
            position = rows.scalars().first()
        assert position.qty == 200
        assert 0.50 < position.avg_price < 0.62

    async def test_no_position_uses_complement_quotes(self, db, engine):
        await seed_market()
        trade = await engine.manual_trade("0xexec1", "NO", "buy", qty=50)
        assert trade.status == "filled"
        # NO ask = 1 - yes_bid = 0.51 (+slippage)
        assert 0.50 < trade.fill_price < 0.55


class TestProtections:
    async def test_stop_loss_closes_losing_position(self, db, engine):
        await seed_market()
        await engine.manual_trade("0xexec1", "YES", "buy", qty=100)  # avg ~0.512
        # collapse the price: loss > 25% stop
        await set_market_price("0xexec1", 0.30, 0.29, 0.31)

        result = await engine.run_protections()
        assert result["stop_losses"] == 1

        async with get_sessionmaker()() as session:
            from sqlalchemy import select

            rows = await session.execute(select(Position).where(Position.status == "open"))
            assert rows.scalars().first() is None

    async def test_hedge_on_drawdown_between_thresholds(self, db, engine):
        await seed_market()
        await engine.manual_trade("0xexec1", "YES", "buy", qty=100)  # avg ~0.512
        # ~18% down: beyond hedge trigger (15%) but inside stop (25%)
        await set_market_price("0xexec1", 0.42, 0.41, 0.43)

        result = await engine.run_protections()
        assert result["stop_losses"] == 0
        assert result["hedges"] == 1

        async with get_sessionmaker()() as session:
            from sqlalchemy import select

            rows = await session.execute(select(Position).where(Position.status == "open"))
            outcomes = {p.outcome for p in rows.scalars()}
        assert outcomes == {"YES", "NO"}

    async def test_healthy_position_untouched(self, db, engine):
        await seed_market()
        await engine.manual_trade("0xexec1", "YES", "buy", qty=100)
        result = await engine.run_protections()
        assert result == {"stop_losses": 0, "hedges": 0}


class TestPortfolioSnapshot:
    async def test_snapshot_written(self, db, engine):
        await seed_market()
        await engine.manual_trade("0xexec1", "YES", "buy", qty=10)
        snap = await engine.snapshot_portfolio()
        assert snap.equity > 0
        assert snap.open_positions == 1
