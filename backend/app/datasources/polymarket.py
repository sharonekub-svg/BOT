"""Polymarket data clients.

- Gamma API  (https://gamma-api.polymarket.com): market/event metadata, prices,
  liquidity, volume. Public, no auth.
- CLOB API   (https://clob.polymarket.com): order books and midpoints per
  outcome token. Public for reads.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.config import get_settings
from app.core.utils import parse_iso_datetime, parse_json_field, safe_float
from app.datasources.base import BaseHTTPClient
from app.logging_config import get_logger

log = get_logger(__name__)

GAMMA_PAGE_SIZE = 500


@dataclass
class GammaMarket:
    """Normalized view of one Gamma market row."""

    condition_id: str
    gamma_id: str | None
    question: str
    slug: str | None
    category: str | None
    event_id: str | None
    event_title: str | None
    neg_risk: bool
    outcomes: list[str]
    clob_token_ids: list[str]
    end_date: datetime | None
    active: bool
    closed: bool
    yes_price: float | None
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    liquidity: float | None
    volume_24h: float | None
    volume_total: float | None
    one_day_change: float | None
    resolved_outcome: str | None = None


@dataclass
class OrderBook:
    token_id: str
    bids: list[tuple[float, float]] = field(default_factory=list)  # (price, size) best first
    asks: list[tuple[float, float]] = field(default_factory=list)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    def depth_within(self, side: str, pct_from_top: float = 0.02) -> float:
        """Notional size available within pct of the top of book — caps arb size."""
        levels = self.bids if side == "bid" else self.asks
        if not levels:
            return 0.0
        top = levels[0][0]
        total = 0.0
        for price, size in levels:
            if abs(price - top) <= pct_from_top:
                total += price * size
        return total


def _normalize_gamma_market(raw: dict) -> GammaMarket | None:
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    question = raw.get("question")
    if not condition_id or not question:
        return None

    outcomes = parse_json_field(raw.get("outcomes"), default=[]) or []
    prices = parse_json_field(raw.get("outcomePrices"), default=[]) or []
    token_ids = parse_json_field(raw.get("clobTokenIds"), default=[]) or []

    yes_price = safe_float(prices[0]) if prices else None
    events = raw.get("events") or []
    event = events[0] if isinstance(events, list) and events else {}

    resolved = None
    if raw.get("closed") and yes_price is not None:
        if yes_price >= 0.99:
            resolved = "Yes"
        elif yes_price <= 0.01:
            resolved = "No"

    return GammaMarket(
        condition_id=str(condition_id),
        gamma_id=str(raw.get("id")) if raw.get("id") is not None else None,
        question=str(question),
        slug=raw.get("slug"),
        category=raw.get("category") or (event.get("category") if isinstance(event, dict) else None),
        event_id=str(event.get("id")) if isinstance(event, dict) and event.get("id") is not None else None,
        event_title=event.get("title") if isinstance(event, dict) else None,
        neg_risk=bool(raw.get("negRisk") or (event.get("negRisk") if isinstance(event, dict) else False)),
        outcomes=[str(o) for o in outcomes],
        clob_token_ids=[str(t) for t in token_ids],
        end_date=parse_iso_datetime(raw.get("endDate")),
        active=bool(raw.get("active", True)),
        closed=bool(raw.get("closed", False)),
        yes_price=yes_price,
        best_bid=safe_float(raw.get("bestBid")),
        best_ask=safe_float(raw.get("bestAsk")),
        spread=safe_float(raw.get("spread")),
        liquidity=safe_float(raw.get("liquidityNum") or raw.get("liquidity")),
        volume_24h=safe_float(raw.get("volume24hr") or raw.get("volume24hrClob")),
        volume_total=safe_float(raw.get("volumeNum") or raw.get("volume")),
        one_day_change=safe_float(raw.get("oneDayPriceChange")),
        resolved_outcome=resolved,
    )


class GammaClient(BaseHTTPClient):
    def __init__(self) -> None:
        super().__init__(get_settings().gamma_base_url)

    async def fetch_active_markets(self, max_markets: int | None = None) -> list[GammaMarket]:
        """Page through all active, open markets ordered by 24h volume."""
        limit = max_markets or get_settings().max_markets_per_scan
        markets: list[GammaMarket] = []
        offset = 0
        while len(markets) < limit:
            page = await self.get_json(
                "/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "archived": "false",
                    "order": "volume24hr",
                    "ascending": "false",
                    "limit": GAMMA_PAGE_SIZE,
                    "offset": offset,
                },
            )
            if not page or not isinstance(page, list):
                break
            for raw in page:
                market = _normalize_gamma_market(raw)
                if market is not None:
                    markets.append(market)
            if len(page) < GAMMA_PAGE_SIZE:
                break
            offset += GAMMA_PAGE_SIZE
        return markets[:limit]

    async def fetch_markets_by_condition(self, condition_ids: list[str]) -> list[GammaMarket]:
        """Refresh specific markets (used to detect resolutions)."""
        results: list[GammaMarket] = []
        for i in range(0, len(condition_ids), 20):
            chunk = condition_ids[i : i + 20]
            page = await self.get_json("/markets", params=[("condition_ids", c) for c in chunk])
            if isinstance(page, list):
                for raw in page:
                    market = _normalize_gamma_market(raw)
                    if market is not None:
                        results.append(market)
        return results


class ClobClient(BaseHTTPClient):
    def __init__(self) -> None:
        super().__init__(get_settings().clob_base_url)

    async def fetch_book(self, token_id: str) -> OrderBook | None:
        data = await self.get_json("/book", params={"token_id": token_id})
        if not data:
            return None
        return self._parse_book(token_id, data)

    async def fetch_books(self, token_ids: list[str]) -> dict[str, OrderBook]:
        """Batch endpoint: POST /books with [{token_id}, ...]."""
        if not token_ids:
            return {}
        payload = [{"token_id": t} for t in token_ids]
        data = await self.post_json("/books", payload)
        books: dict[str, OrderBook] = {}
        if isinstance(data, list):
            for entry in data:
                token = str(entry.get("asset_id") or entry.get("token_id") or "")
                if token:
                    books[token] = self._parse_book(token, entry)
        return books

    @staticmethod
    def _parse_book(token_id: str, data: dict) -> OrderBook:
        def levels(raw: Any, reverse: bool) -> list[tuple[float, float]]:
            out = []
            for lvl in raw or []:
                price = safe_float(lvl.get("price"))
                size = safe_float(lvl.get("size"))
                if price is not None and size is not None:
                    out.append((price, size))
            return sorted(out, key=lambda x: x[0], reverse=reverse)

        return OrderBook(
            token_id=token_id,
            bids=levels(data.get("bids"), reverse=True),   # best bid = highest
            asks=levels(data.get("asks"), reverse=False),  # best ask = lowest
        )
