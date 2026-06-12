"""Binance public client — real-time spot prices and klines for crypto markets."""

from app.config import get_settings
from app.core.utils import safe_float
from app.datasources.base import BaseHTTPClient


class BinanceClient(BaseHTTPClient):
    def __init__(self) -> None:
        super().__init__(get_settings().binance_base_url)

    async def ticker_price(self, symbol: str) -> float | None:
        data = await self.get_json("/api/v3/ticker/price", params={"symbol": symbol.upper()})
        return safe_float((data or {}).get("price"))

    async def ticker_24h(self, symbol: str) -> dict | None:
        return await self.get_json("/api/v3/ticker/24hr", params={"symbol": symbol.upper()})

    async def klines(self, symbol: str, interval: str = "1h", limit: int = 168) -> list[dict]:
        data = await self.get_json(
            "/api/v3/klines", params={"symbol": symbol.upper(), "interval": interval, "limit": limit}
        )
        out = []
        for row in data or []:
            out.append(
                {
                    "open_time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        return out
