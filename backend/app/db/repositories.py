"""Data-access helpers shared by workers and API routers."""

from datetime import datetime, timedelta

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import now_utc
from app.db.models import (
    AIAnalysis,
    ArbitrageOpportunity,
    Market,
    MarketEvent,
    MarketRelationship,
    MarketSnapshot,
    PortfolioSnapshot,
    Position,
    PredictionRecord,
    Signal,
    Trade,
)

# ---------------------------------------------------------------- markets


async def upsert_market(session: AsyncSession, data: dict) -> Market:
    market = await session.get(Market, data["id"])
    if market is None:
        market = Market(**data)
        session.add(market)
    else:
        for key, value in data.items():
            if key != "id":
                setattr(market, key, value)
    return market


async def get_market(session: AsyncSession, market_id: str) -> Market | None:
    return await session.get(Market, market_id)


async def list_active_markets(session: AsyncSession, limit: int = 5000) -> list[Market]:
    rows = await session.execute(
        select(Market).where(Market.active.is_(True), Market.closed.is_(False)).limit(limit)
    )
    return list(rows.scalars())


# ---------------------------------------------------------------- snapshots


async def add_snapshot(session: AsyncSession, **kwargs) -> MarketSnapshot:
    snap = MarketSnapshot(**kwargs)
    session.add(snap)
    return snap


async def recent_snapshots(
    session: AsyncSession, market_id: str, since: datetime | None = None, limit: int = 500
) -> list[MarketSnapshot]:
    stmt = select(MarketSnapshot).where(MarketSnapshot.market_id == market_id)
    if since is not None:
        stmt = stmt.where(MarketSnapshot.ts >= since)
    stmt = stmt.order_by(desc(MarketSnapshot.ts)).limit(limit)
    rows = await session.execute(stmt)
    return list(reversed(list(rows.scalars())))  # chronological order


async def prune_snapshots(session: AsyncSession, older_than_days: int) -> int:
    cutoff = now_utc() - timedelta(days=older_than_days)
    result = await session.execute(delete(MarketSnapshot).where(MarketSnapshot.ts < cutoff))
    return result.rowcount or 0


# ---------------------------------------------------------------- signals


async def expire_active_signals(session: AsyncSession, market_id: str) -> None:
    await session.execute(
        update(Signal)
        .where(Signal.market_id == market_id, Signal.status == "active")
        .values(status="expired")
    )


async def insert_signal(session: AsyncSession, **kwargs) -> Signal:
    signal = Signal(**kwargs)
    session.add(signal)
    return signal


async def top_signals(
    session: AsyncSession, limit: int = 50, min_edge: float = 0.0, status: str = "active"
) -> list[tuple[Signal, Market]]:
    stmt = (
        select(Signal, Market)
        .join(Market, Signal.market_id == Market.id)
        .where(Signal.status == status, Signal.edge_score >= min_edge)
        .order_by(desc(Signal.edge_score))
        .limit(limit)
    )
    rows = await session.execute(stmt)
    return [(s, m) for s, m in rows.all()]


# ---------------------------------------------------------------- AI


async def latest_analysis(session: AsyncSession, market_id: str) -> AIAnalysis | None:
    rows = await session.execute(
        select(AIAnalysis)
        .where(AIAnalysis.market_id == market_id)
        .order_by(desc(AIAnalysis.ts))
        .limit(1)
    )
    return rows.scalars().first()


# ---------------------------------------------------------------- portfolio


async def open_positions(session: AsyncSession) -> list[Position]:
    rows = await session.execute(select(Position).where(Position.status == "open"))
    return list(rows.scalars())


async def position_for(session: AsyncSession, market_id: str, outcome: str) -> Position | None:
    rows = await session.execute(
        select(Position).where(
            Position.market_id == market_id,
            Position.outcome == outcome,
            Position.status == "open",
        )
    )
    return rows.scalars().first()


async def latest_portfolio(session: AsyncSession) -> PortfolioSnapshot | None:
    rows = await session.execute(
        select(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.ts)).limit(1)
    )
    return rows.scalars().first()


async def realized_pnl_between(session: AsyncSession, start: datetime, end: datetime) -> float:
    """Realized PnL from sells minus fees over a window (paper accounting)."""
    rows = await session.execute(
        select(Position.realized_pnl).where(
            Position.closed_at.isnot(None),
            Position.closed_at >= start,
            Position.closed_at <= end,
        )
    )
    return float(sum(v or 0.0 for v in rows.scalars()))


async def trades_history(session: AsyncSession, limit: int = 200) -> list[Trade]:
    rows = await session.execute(select(Trade).order_by(desc(Trade.created_at)).limit(limit))
    return list(rows.scalars())


# ---------------------------------------------------------------- misc


async def insert_market_event(session: AsyncSession, **kwargs) -> MarketEvent:
    event = MarketEvent(**kwargs)
    session.add(event)
    return event


async def active_arbitrage(session: AsyncSession, limit: int = 50) -> list[ArbitrageOpportunity]:
    rows = await session.execute(
        select(ArbitrageOpportunity)
        .where(ArbitrageOpportunity.status == "active")
        .order_by(desc(ArbitrageOpportunity.net_edge))
        .limit(limit)
    )
    return list(rows.scalars())


async def expire_arbitrage(session: AsyncSession) -> None:
    await session.execute(
        update(ArbitrageOpportunity)
        .where(ArbitrageOpportunity.status == "active")
        .values(status="expired")
    )


async def replace_relationships(session: AsyncSession, edges: list[dict]) -> None:
    await session.execute(delete(MarketRelationship))
    for edge in edges:
        session.add(MarketRelationship(**edge))


async def relationships(session: AsyncSession, limit: int = 2000) -> list[MarketRelationship]:
    rows = await session.execute(select(MarketRelationship).limit(limit))
    return list(rows.scalars())


async def unresolved_predictions(session: AsyncSession) -> list[PredictionRecord]:
    rows = await session.execute(select(PredictionRecord).where(PredictionRecord.outcome.is_(None)))
    return list(rows.scalars())


async def count_rows(session: AsyncSession, model) -> int:
    rows = await session.execute(select(func.count()).select_from(model))
    return int(rows.scalar() or 0)
