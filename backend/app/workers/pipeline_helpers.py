"""Query/feature helpers used by the orchestrator loops."""

from datetime import timedelta

import numpy as np
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import as_utc, hours_until, now_utc
from app.db import repositories as repo
from app.db.models import AIAnalysis, Market, MarketSnapshot, MLModelRecord
from app.edge.engine import EdgeResult, FairEstimate
from app.ml.features import build_features
from app.ml.models import MODEL_NAME, TrainReport


def signal_rationale(result: EdgeResult, estimates: list[FairEstimate]) -> str:
    sources = ", ".join(f"{e.source}={e.prob:.2f}(c{e.confidence:.1f})" for e in estimates) or "market-only"
    return (
        f"fair {result.fair_prob:.2f} vs implied {result.implied_prob:.2f}; "
        f"EV {result.expected_value * 100:+.1f}%; estimates: {sources}"
    )


async def ai_candidates(session: AsyncSession, limit: int, cooldown_minutes: int) -> list[Market]:
    """Most interesting markets to spend AI budget on: liquid, active, with a
    live edge-engine signal or recent anomaly, not analyzed too recently."""
    markets = await repo.list_active_markets(session)
    scored: list[tuple[float, Market]] = []
    cutoff = now_utc() - timedelta(minutes=cooldown_minutes)

    for market in markets:
        if not market.liquidity or market.liquidity < 1000:
            continue
        if market.yes_price is None or not (0.03 < market.yes_price < 0.97):
            continue
        interest = (market.volume_24h or 0.0) / 1000.0
        if market.one_day_change:
            interest += abs(market.one_day_change) * 100
        scored.append((interest, market))

    scored.sort(key=lambda pair: -pair[0])
    selected: list[Market] = []
    for _, market in scored:
        if len(selected) >= limit:
            break
        analysis = await repo.latest_analysis(session, market.id)
        if analysis is not None and as_utc(analysis.ts) > cutoff:
            continue
        selected.append(market)
    return selected


async def features_for_market(session: AsyncSession, market: Market) -> list[float] | None:
    snaps = await repo.recent_snapshots(session, market.id, limit=48)
    if len(snaps) < 4:
        return None
    return build_features(
        prices=[s.yes_price for s in snaps],
        spreads=[s.spread for s in snaps],
        liquidity=[s.liquidity for s in snaps],
        volumes=[s.volume_24h for s in snaps],
        days_to_end=(hours_until(market.end_date) or 720) / 24.0,
    )


async def series_inputs(session: AsyncSession, max_markets: int = 300, hours: int = 72):
    """Minute-bucketed price series for the relationship graph."""
    from app.graph.relationships import SeriesInput

    markets = await repo.list_active_markets(session)
    markets.sort(key=lambda m: -(m.volume_24h or 0))
    markets = markets[:max_markets]
    since = now_utc() - timedelta(hours=hours)

    inputs: list[SeriesInput] = []
    for market in markets:
        snaps = await repo.recent_snapshots(session, market.id, since=since, limit=500)
        series = [
            (int(as_utc(s.ts).timestamp() // 600), s.yes_price)  # 10-minute buckets
            for s in snaps
            if s.yes_price is not None
        ]
        inputs.append(SeriesInput(market.id, market.event_id, market.question, series))
    return inputs


async def training_matrix(session: AsyncSession) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Build (X, y) from resolved markets' snapshot history."""
    rows = await session.execute(
        select(Market).where(Market.resolved_outcome.isnot(None)).limit(5000)
    )
    X_rows: list[list[float]] = []
    y_rows: list[int] = []
    for market in rows.scalars():
        snaps = await repo.recent_snapshots(session, market.id, limit=48)
        if len(snaps) < 4:
            continue
        features = build_features(
            prices=[s.yes_price for s in snaps],
            spreads=[s.spread for s in snaps],
            liquidity=[s.liquidity for s in snaps],
            volumes=[s.volume_24h for s in snaps],
            days_to_end=1.0,
        )
        if features is None:
            continue
        X_rows.append(features)
        y_rows.append(1 if market.resolved_outcome == "Yes" else 0)
    if not X_rows:
        return None, None
    return np.asarray(X_rows, dtype=float), np.asarray(y_rows, dtype=int)


async def record_model(session: AsyncSession, report: TrainReport) -> None:
    rows = await session.execute(
        select(MLModelRecord).where(MLModelRecord.name == MODEL_NAME).order_by(desc(MLModelRecord.version)).limit(1)
    )
    last = rows.scalars().first()
    session.add(
        MLModelRecord(
            name=MODEL_NAME,
            version=(last.version + 1) if last else 1,
            trained_at=now_utc(),
            n_samples=report.n_samples,
            metrics={
                "brier": report.brier,
                "log_loss": report.log_loss,
                "baseline_brier": report.baseline_brier,
            },
            path=report.path,
        )
    )


async def latest_ai_analyses(session: AsyncSession, limit: int = 20) -> list[AIAnalysis]:
    rows = await session.execute(select(AIAnalysis).order_by(desc(AIAnalysis.ts)).limit(limit))
    return list(rows.scalars())


async def snapshot_count(session: AsyncSession) -> int:
    return await repo.count_rows(session, MarketSnapshot)
