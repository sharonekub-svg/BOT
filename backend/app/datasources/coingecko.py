"""CoinGecko client — reference prices for crypto-linked markets."""

from app.config import get_settings
from app.core.utils import safe_float
from app.datasources.base import BaseHTTPClient


class CoinGeckoClient(BaseHTTPClient):
    def __init__(self) -> None:
        super().__init__(get_settings().coingecko_base_url)

    async def simple_prices(self, coin_ids: list[str], vs: str = "usd") -> dict[str, float]:
        data = await self.get_json(
            "/simple/price",
            params={"ids": ",".join(coin_ids), "vs_currencies": vs, "include_24hr_change": "true"},
        )
        out: dict[str, float] = {}
        for coin, payload in (data or {}).items():
            price = safe_float(payload.get(vs))
            if price is not None:
                out[coin] = price
        return out

    async def market_chart(self, coin_id: str, days: int = 7, vs: str = "usd") -> list[tuple[int, float]]:
        data = await self.get_json(f"/coins/{coin_id}/market_chart", params={"vs_currency": vs, "days": days})
        prices = (data or {}).get("prices") or []
        return [(int(ts), float(price)) for ts, price in prices]
