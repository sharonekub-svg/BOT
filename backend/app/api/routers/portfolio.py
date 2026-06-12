"""Portfolio API: positions, trades, P&L, risk exposure, manual orders."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.utils import now_utc
from app.db import repositories as repo
from app.db.base import get_session
from app.db.models import PortfolioSnapshot
from app.execution.engine import ExecutionEngine, mark_price

router = APIRouter(prefix="/api/v1", tags=["portfolio"])

_engine: ExecutionEngine | None = None


def get_execution() -> ExecutionEngine:
    global _engine
    if _engine is None:
        _engine = ExecutionEngine()
    return _engine


@router.get("/portfolio")
async def portfolio(session: AsyncSession = Depends(get_session)):
    snap = await repo.latest_portfolio(session)
    settings = get_settings()
    if snap is None:
        return {
            "equity": settings.starting_bankroll,
            "cash": settings.starting_bankroll,
            "exposure": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl_today": 0.0,
            "drawdown": 0.0,
            "open_positions": 0,
            "starting_bankroll": settings.starting_bankroll,
            "mode": settings.trading_mode,
        }
    return {
        "equity": snap.equity,
        "cash": snap.cash,
        "exposure": snap.exposure,
        "unrealized_pnl": snap.unrealized_pnl,
        "realized_pnl_today": snap.realized_pnl_today,
        "drawdown": snap.drawdown,
        "peak_equity": snap.peak_equity,
        "open_positions": snap.open_positions,
        "starting_bankroll": settings.starting_bankroll,
        "mode": settings.trading_mode,
        "ts": snap.ts.isoformat(),
    }


@router.get("/portfolio/history")
async def portfolio_history(
    hours: int = Query(168, le=24 * 365), session: AsyncSession = Depends(get_session)
):
    rows = await session.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.ts >= now_utc() - timedelta(hours=hours))
        .order_by(PortfolioSnapshot.ts)
    )
    return {
        "points": [
            {"ts": s.ts.isoformat(), "equity": s.equity, "exposure": s.exposure, "drawdown": s.drawdown}
            for s in rows.scalars()
        ]
    }


@router.get("/positions")
async def positions(session: AsyncSession = Depends(get_session)):
    out = []
    for pos in await repo.open_positions(session):
        market = await repo.get_market(session, pos.market_id)
        current = mark_price(pos.outcome, market.yes_price if market else None)
        value = (current if current is not None else pos.avg_price) * pos.qty
        out.append(
            {
                "id": pos.id,
                "market_id": pos.market_id,
                "question": market.question if market else pos.market_id,
                "category": market.category if market else None,
                "outcome": pos.outcome,
                "qty": pos.qty,
                "avg_price": pos.avg_price,
                "current_price": current,
                "value": round(value, 2),
                "unrealized_pnl": round((current - pos.avg_price) * pos.qty, 2)
                if current is not None
                else None,
                "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            }
        )
    out.sort(key=lambda p: -(p["value"] or 0))
    return {"positions": out}


@router.post("/positions/{position_id}/close")
async def close_position(position_id: int):
    trade = await get_execution().close_position(position_id, reason="manual_close")
    if trade is None:
        raise HTTPException(404, "position not found or not open")
    return {"status": trade.status, "fill_price": trade.fill_price, "qty": trade.qty}


@router.get("/trades")
async def trades(limit: int = Query(100, le=500), session: AsyncSession = Depends(get_session)):
    rows = await repo.trades_history(session, limit=limit)
    out = []
    for t in rows:
        market = await repo.get_market(session, t.market_id)
        out.append(
            {
                "id": t.id,
                "market_id": t.market_id,
                "question": market.question if market else t.market_id,
                "mode": t.mode,
                "side": t.side,
                "outcome": t.outcome,
                "order_type": t.order_type,
                "qty": t.qty,
                "fill_price": t.fill_price,
                "notional": t.notional,
                "fee": t.fee,
                "status": t.status,
                "reason": t.reason,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
        )
    return {"trades": out}


class TradeRequest(BaseModel):
    market_id: str
    outcome: str = Field(pattern="^(YES|NO|yes|no)$")
    side: str = Field(pattern="^(buy|sell)$")
    qty: float = Field(gt=0)
    order_type: str = Field(default="market", pattern="^(market|limit)$")
    limit_price: float | None = Field(default=None, gt=0, lt=1)


@router.post("/trades")
async def place_trade(body: TradeRequest):
    try:
        trade = await get_execution().manual_trade(
            market_id=body.market_id,
            outcome=body.outcome,
            side=body.side,
            qty=body.qty,
            order_type=body.order_type,
            limit_price=body.limit_price,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if trade is None:
        raise HTTPException(400, "trade could not be placed")
    return {
        "id": trade.id,
        "status": trade.status,
        "fill_price": trade.fill_price,
        "order_id": trade.order_id,
    }


@router.get("/risk")
async def risk(session: AsyncSession = Depends(get_session)):
    engine = get_execution()
    state = await engine.portfolio_state(session)
    warnings = engine.risk.check_portfolio_health(state)
    settings = get_settings()
    equity = max(state.equity, 1e-9)
    return {
        "equity": round(state.equity, 2),
        "cash": round(state.cash, 2),
        "total_exposure": round(state.total_exposure, 2),
        "total_exposure_pct": round(state.total_exposure / equity * 100, 2),
        "exposure_by_category": {
            k: round(v, 2) for k, v in sorted(state.exposure_by_category.items(), key=lambda kv: -kv[1])
        },
        "exposure_by_market": {
            k: round(v, 2)
            for k, v in sorted(state.exposure_by_market.items(), key=lambda kv: -kv[1])[:20]
        },
        "open_positions": state.open_positions,
        "daily_pnl": round(state.daily_pnl, 2),
        "drawdown_pct": round(state.drawdown * 100, 2),
        "circuit_breaker_tripped": engine.risk.circuit_breaker_tripped,
        "warnings": warnings,
        "limits": {
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
            "max_market_exposure_pct": settings.max_market_exposure_pct,
            "max_category_exposure_pct": settings.max_category_exposure_pct,
            "max_total_exposure_pct": settings.max_total_exposure_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_drawdown_pct": settings.max_drawdown_pct,
            "max_open_positions": settings.max_open_positions,
            "kelly_fraction": settings.kelly_fraction,
        },
    }


@router.post("/risk/reset-circuit-breaker")
async def reset_circuit_breaker():
    get_execution().risk.reset_circuit_breaker()
    return {"circuit_breaker_tripped": False}
