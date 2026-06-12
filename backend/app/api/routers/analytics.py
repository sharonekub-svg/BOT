"""Analytics API: performance metrics, prediction calibration, backtests."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.engine import Backtester, BacktestMarket
from app.backtest.metrics import summarize
from app.backtest.strategies import STRATEGIES, BacktestSnapshot
from app.core.utils import as_utc, now_utc
from app.db import repositories as repo
from app.db.base import get_session, session_scope
from app.db.models import BacktestRun, Market, PortfolioSnapshot, Position, PredictionRecord
from app.ml.evaluation import evaluate_predictions

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/performance")
async def performance(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.ts))
    snaps = list(rows.scalars())
    equity_curve = [s.equity for s in snaps]
    n_days = 1.0
    if len(snaps) >= 2:
        n_days = max(
            (as_utc(snaps[-1].ts) - as_utc(snaps[0].ts)).total_seconds() / 86400.0, 1.0
        )

    closed = await session.execute(select(Position).where(Position.status == "closed"))
    pnls = [p.realized_pnl for p in closed.scalars()]

    return {
        "metrics": summarize(equity_curve or [0.0], n_days, pnls),
        "n_snapshots": len(snaps),
        "window_days": round(n_days, 1),
    }


@router.get("/calibration")
async def calibration(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(PredictionRecord).order_by(desc(PredictionRecord.ts)).limit(5000))
    records = [
        {
            "model_prob": r.model_prob,
            "ai_prob": r.ai_prob,
            "market_prob": r.market_prob,
            "outcome": r.outcome,
        }
        for r in rows.scalars()
    ]
    report = evaluate_predictions(records)
    return {
        "n_resolved": report.n,
        "brier_model": report.brier_model,
        "brier_ai": report.brier_ai,
        "brier_market": report.brier_market,
        "model_beats_market": report.model_beats_market,
        "ai_beats_market": report.ai_beats_market,
        "reliability": report.buckets,
        "n_total_predictions": len(records),
    }


class BacktestRequest(BaseModel):
    name: str = "ad-hoc"
    strategy: str = Field(default="mean_reversion")
    starting_bankroll: float = Field(default=10_000.0, gt=0)
    kelly_multiplier: float = Field(default=0.25, gt=0, le=1)
    max_risk_pct: float = Field(default=2.0, gt=0, le=100)
    fee_rate: float = Field(default=0.0, ge=0, le=0.1)
    max_markets: int = Field(default=500, le=5000)


@router.post("/backtests")
async def run_backtest(body: BacktestRequest, session: AsyncSession = Depends(get_session)):
    if body.strategy not in STRATEGIES:
        raise HTTPException(400, f"unknown strategy; available: {sorted(STRATEGIES)}")

    rows = await session.execute(
        select(Market).where(Market.resolved_outcome.isnot(None)).limit(body.max_markets)
    )
    markets: list[BacktestMarket] = []
    for market in rows.scalars():
        snaps = await repo.recent_snapshots(session, market.id, limit=500)
        if len(snaps) < 5:
            continue
        end = market.end_date
        markets.append(
            BacktestMarket(
                market_id=market.id,
                question=market.question,
                outcome=1 if market.resolved_outcome == "Yes" else 0,
                resolved_at=end,
                snapshots=[
                    BacktestSnapshot(
                        ts=as_utc(s.ts).isoformat(),
                        yes_price=s.yes_price or 0.5,
                        best_bid=s.best_bid,
                        best_ask=s.best_ask,
                        liquidity=s.liquidity or 0.0,
                        volume_24h=s.volume_24h or 0.0,
                        hours_to_resolution=(
                            (as_utc(end) - as_utc(s.ts)).total_seconds() / 3600 if end else None
                        ),
                    )
                    for s in snaps
                ],
            )
        )
    if not markets:
        raise HTTPException(400, "no resolved markets with history — run the scanner first or seed demo data")

    backtester = Backtester(
        starting_bankroll=body.starting_bankroll,
        kelly_multiplier=body.kelly_multiplier,
        max_risk_pct=body.max_risk_pct,
        fee_rate=body.fee_rate,
    )
    strategy = STRATEGIES[body.strategy]()
    result = await asyncio.to_thread(backtester.run, markets, strategy)

    async with session_scope() as write_session:
        run = BacktestRun(
            created_at=now_utc(),
            name=body.name,
            strategy=body.strategy,
            params=body.model_dump(),
            start=None,
            end=None,
            status="completed",
            metrics=result.metrics,
            equity_curve=result.equity_curve[-2000:],
        )
        write_session.add(run)
        await write_session.flush()
        run_id = run.id

    return {"id": run_id, "metrics": result.metrics, "n_markets": len(markets),
            "equity_curve": result.equity_curve[-500:]}


@router.get("/backtests")
async def list_backtests(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(50))
    return {
        "backtests": [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat(),
                "name": r.name,
                "strategy": r.strategy,
                "metrics": r.metrics,
            }
            for r in rows.scalars()
        ]
    }


@router.get("/backtests/{run_id}")
async def backtest_detail(run_id: int, session: AsyncSession = Depends(get_session)):
    run = await session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(404, "backtest not found")
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat(),
        "name": run.name,
        "strategy": run.strategy,
        "params": run.params,
        "metrics": run.metrics,
        "equity_curve": run.equity_curve,
    }
