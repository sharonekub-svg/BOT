"""Markets API: listing, detail, history, anomalies, heatmap."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import now_utc
from app.db import repositories as repo
from app.db.base import get_session
from app.db.models import AIAnalysis, Market, MarketEvent

router = APIRouter(prefix="/api/v1/markets", tags=["markets"])


def market_to_dict(m: Market) -> dict:
    return {
        "id": m.id,
        "question": m.question,
        "slug": m.slug,
        "category": m.category,
        "event_id": m.event_id,
        "event_title": m.event_title,
        "neg_risk": m.neg_risk,
        "outcomes": m.outcomes,
        "end_date": m.end_date.isoformat() if m.end_date else None,
        "active": m.active,
        "closed": m.closed,
        "resolved_outcome": m.resolved_outcome,
        "yes_price": m.yes_price,
        "best_bid": m.best_bid,
        "best_ask": m.best_ask,
        "spread": m.spread,
        "liquidity": m.liquidity,
        "volume_24h": m.volume_24h,
        "volume_total": m.volume_total,
        "one_day_change": m.one_day_change,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.get("")
async def list_markets(
    session: AsyncSession = Depends(get_session),
    search: str | None = None,
    category: str | None = None,
    sort: str = Query("volume_24h", pattern="^(volume_24h|liquidity|one_day_change|end_date)$"),
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    stmt = select(Market).where(Market.active.is_(True), Market.closed.is_(False))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Market.question.ilike(like), Market.event_title.ilike(like)))
    if category:
        stmt = stmt.where(Market.category == category)
    column = getattr(Market, sort)
    stmt = stmt.order_by(desc(column).nulls_last()).limit(limit).offset(offset)
    rows = await session.execute(stmt)
    return {"markets": [market_to_dict(m) for m in rows.scalars()]}


@router.get("/heatmap")
async def heatmap(session: AsyncSession = Depends(get_session), limit: int = Query(60, le=200)):
    rows = await session.execute(
        select(Market)
        .where(Market.active.is_(True), Market.closed.is_(False))
        .order_by(desc(Market.volume_24h).nulls_last())
        .limit(limit)
    )
    return {
        "tiles": [
            {
                "id": m.id,
                "question": m.question,
                "category": m.category or "other",
                "yes_price": m.yes_price,
                "change": m.one_day_change,
                "volume_24h": m.volume_24h,
            }
            for m in rows.scalars()
        ]
    }


@router.get("/categories")
async def categories(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(Market.category).where(Market.active.is_(True)).distinct()
    )
    return {"categories": sorted({c for c in rows.scalars() if c})}


@router.get("/{market_id}")
async def market_detail(market_id: str, session: AsyncSession = Depends(get_session)):
    market = await repo.get_market(session, market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    analysis = await repo.latest_analysis(session, market_id)
    return {
        "market": market_to_dict(market),
        "latest_ai_analysis": {
            "ts": analysis.ts.isoformat(),
            "model": analysis.model,
            "probability_estimate": analysis.probability_estimate,
            "confidence": analysis.confidence,
            "signal": analysis.signal,
            "reasoning": analysis.reasoning,
            "key_factors": analysis.key_factors,
            "contradictions": analysis.contradictions,
        }
        if analysis
        else None,
    }


@router.get("/{market_id}/history")
async def market_history(
    market_id: str,
    hours: int = Query(168, le=24 * 90),
    session: AsyncSession = Depends(get_session),
):
    market = await repo.get_market(session, market_id)
    if market is None:
        raise HTTPException(404, "market not found")
    snaps = await repo.recent_snapshots(session, market_id, since=now_utc() - timedelta(hours=hours))
    return {
        "market_id": market_id,
        "points": [
            {
                "ts": s.ts.isoformat(),
                "yes_price": s.yes_price,
                "liquidity": s.liquidity,
                "volume_24h": s.volume_24h,
                "spread": s.spread,
            }
            for s in snaps
        ],
    }


@router.get("/{market_id}/anomalies")
async def market_anomalies(market_id: str, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(MarketEvent)
        .where(MarketEvent.market_id == market_id)
        .order_by(desc(MarketEvent.ts))
        .limit(50)
    )
    return {
        "anomalies": [
            {"ts": e.ts.isoformat(), "kind": e.kind, "severity": e.severity, "detail": e.payload}
            for e in rows.scalars()
        ]
    }


@router.get("/{market_id}/analyses")
async def market_analyses(market_id: str, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(AIAnalysis)
        .where(AIAnalysis.market_id == market_id)
        .order_by(desc(AIAnalysis.ts))
        .limit(20)
    )
    return {
        "analyses": [
            {
                "ts": a.ts.isoformat(),
                "model": a.model,
                "probability_estimate": a.probability_estimate,
                "confidence": a.confidence,
                "signal": a.signal,
                "reasoning": a.reasoning,
                "key_factors": a.key_factors,
                "contradictions": a.contradictions,
                "news_sentiment": a.news_sentiment,
                "social_sentiment": a.social_sentiment,
            }
            for a in rows.scalars()
        ]
    }
