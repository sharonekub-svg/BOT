"""Opportunities API: ranked signals and live arbitrage."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories as repo
from app.db.base import get_session

router = APIRouter(prefix="/api/v1", tags=["opportunities"])


@router.get("/opportunities")
async def opportunities(
    session: AsyncSession = Depends(get_session),
    min_edge: float = Query(0.0, ge=0, le=100),
    limit: int = Query(50, le=200),
):
    ranked = await repo.top_signals(session, limit=limit, min_edge=min_edge)
    return {
        "opportunities": [
            {
                "signal_id": signal.id,
                "market_id": market.id,
                "question": market.question,
                "category": market.category,
                "direction": signal.direction,
                "edge_score": signal.edge_score,
                "implied_prob": signal.implied_prob,
                "fair_prob": signal.fair_prob,
                "expected_value": signal.expected_value,
                "kelly_size": signal.kelly_size,
                "confidence": signal.confidence,
                "liquidity": market.liquidity,
                "volume_24h": market.volume_24h,
                "end_date": market.end_date.isoformat() if market.end_date else None,
                "rationale": signal.rationale,
                "components": signal.components,
                "source": signal.source,
                "ts": signal.ts.isoformat(),
            }
            for signal, market in ranked
        ]
    }


@router.get("/arbitrage")
async def arbitrage(session: AsyncSession = Depends(get_session), limit: int = Query(50, le=200)):
    rows = await repo.active_arbitrage(session, limit=limit)
    return {
        "arbitrage": [
            {
                "id": a.id,
                "ts": a.ts.isoformat(),
                "kind": a.kind,
                "market_ids": a.market_ids,
                "legs": a.legs,
                "gross_edge": a.gross_edge,
                "net_edge": a.net_edge,
                "size_cap": a.size_cap,
                "description": a.description,
            }
            for a in rows
        ]
    }
