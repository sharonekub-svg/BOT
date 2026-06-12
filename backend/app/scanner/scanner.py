"""Market scanner — keeps the local mirror of Polymarket fresh.

Each cycle:
1. Pull all active markets from Gamma (paginated, volume-ordered).
2. Refresh CLOB order books for the top-N most liquid markets.
3. Upsert markets, append snapshots (price history), detect anomalies.
4. Detect resolutions for markets we track that just closed.
5. Publish ticks to the event bus for the dashboard live feed.
"""

from dataclasses import dataclass

from app.config import get_settings
from app.core.events import get_event_bus
from app.core.utils import now_utc
from app.datasources.polymarket import ClobClient, GammaClient, GammaMarket, OrderBook
from app.db import repositories as repo
from app.db.base import session_scope
from app.logging_config import get_logger
from app.scanner.anomaly import Anomaly, AnomalyDetector

log = get_logger(__name__)


@dataclass
class ScanResult:
    markets_seen: int
    snapshots_written: int
    anomalies: list[Anomaly]
    resolved: list[str]


class MarketScanner:
    def __init__(
        self,
        gamma: GammaClient | None = None,
        clob: ClobClient | None = None,
        detector: AnomalyDetector | None = None,
    ) -> None:
        self.settings = get_settings()
        self.gamma = gamma or GammaClient()
        self.clob = clob or ClobClient()
        self.detector = detector or AnomalyDetector()
        self._known_active: set[str] = set()

    async def scan_once(self) -> ScanResult:
        markets = await self.gamma.fetch_active_markets()
        if not markets:
            log.warning("scan produced no markets (Gamma unreachable?)")
            return ScanResult(0, 0, [], [])

        books = await self._refresh_books(markets[: self.settings.orderbook_top_n])
        anomalies: list[Anomaly] = []
        resolved: list[str] = []
        snapshots = 0
        ts = now_utc()

        async with session_scope() as session:
            seen_ids = set()
            for gm in markets:
                seen_ids.add(gm.condition_id)
                best_bid, best_ask = gm.best_bid, gm.best_ask
                yes_token = gm.clob_token_ids[0] if gm.clob_token_ids else None
                book = books.get(yes_token) if yes_token else None
                if book is not None:
                    best_bid = book.best_bid if book.best_bid is not None else best_bid
                    best_ask = book.best_ask if book.best_ask is not None else best_ask

                mid = None
                if best_bid is not None and best_ask is not None:
                    mid = (best_bid + best_ask) / 2
                yes_price = gm.yes_price if gm.yes_price is not None else mid

                await repo.upsert_market(
                    session,
                    {
                        "id": gm.condition_id,
                        "gamma_id": gm.gamma_id,
                        "question": gm.question,
                        "slug": gm.slug,
                        "category": gm.category,
                        "event_id": gm.event_id,
                        "event_title": gm.event_title,
                        "neg_risk": gm.neg_risk,
                        "outcomes": gm.outcomes,
                        "clob_token_ids": gm.clob_token_ids,
                        "end_date": gm.end_date,
                        "active": gm.active,
                        "closed": gm.closed,
                        "yes_price": yes_price,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread": (best_ask - best_bid)
                        if (best_ask is not None and best_bid is not None)
                        else gm.spread,
                        "liquidity": gm.liquidity,
                        "volume_24h": gm.volume_24h,
                        "volume_total": gm.volume_total,
                        "one_day_change": gm.one_day_change,
                    },
                )
                await repo.add_snapshot(
                    session,
                    market_id=gm.condition_id,
                    ts=ts,
                    yes_price=yes_price,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    spread=(best_ask - best_bid)
                    if (best_ask is not None and best_bid is not None)
                    else gm.spread,
                    liquidity=gm.liquidity,
                    volume_24h=gm.volume_24h,
                )
                snapshots += 1

                for anomaly in self.detector.observe(
                    gm.condition_id, yes_price, gm.volume_24h, gm.liquidity
                ):
                    anomalies.append(anomaly)
                    await repo.insert_market_event(
                        session,
                        market_id=anomaly.market_id,
                        ts=ts,
                        kind=anomaly.kind,
                        severity=anomaly.severity,
                        payload=anomaly.detail,
                    )

            resolved = await self._detect_resolutions(session, seen_ids)

        bus = get_event_bus()
        await bus.publish(
            "scan_complete",
            {"markets": len(markets), "snapshots": snapshots, "anomalies": len(anomalies)},
        )
        for anomaly in anomalies[:20]:
            await bus.publish("anomaly", {"market_id": anomaly.market_id, "kind": anomaly.kind,
                                          "severity": anomaly.severity, **anomaly.detail})
        self._known_active = seen_ids
        return ScanResult(len(markets), snapshots, anomalies, resolved)

    async def _refresh_books(self, top_markets: list[GammaMarket]) -> dict[str, OrderBook]:
        token_ids = [m.clob_token_ids[0] for m in top_markets if m.clob_token_ids]
        if not token_ids:
            return {}
        books: dict[str, OrderBook] = {}
        for i in range(0, len(token_ids), 50):
            books.update(await self.clob.fetch_books(token_ids[i : i + 50]))
        return books

    async def _detect_resolutions(self, session, currently_active: set[str]) -> list[str]:
        """Markets we tracked that vanished from the active set likely resolved."""
        if not self._known_active:
            return []
        disappeared = list(self._known_active - currently_active)[:100]
        if not disappeared:
            return []
        refreshed = await self.gamma.fetch_markets_by_condition(disappeared)
        resolved_ids: list[str] = []
        for gm in refreshed:
            if gm.closed and gm.resolved_outcome:
                market = await repo.get_market(session, gm.condition_id)
                if market is not None:
                    market.closed = True
                    market.active = False
                    market.resolved_outcome = gm.resolved_outcome
                    resolved_ids.append(gm.condition_id)
        if resolved_ids:
            log.info("detected %d resolutions", len(resolved_ids))
        return resolved_ids

    async def prune_history(self) -> int:
        async with session_scope() as session:
            removed = await repo.prune_snapshots(session, self.settings.snapshot_retention_days)
        if removed:
            log.info("pruned %d snapshots older than %dd", removed, self.settings.snapshot_retention_days)
        return removed

    async def close(self) -> None:
        await self.gamma.close()
        await self.clob.close()
