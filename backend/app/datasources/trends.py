"""Google Trends interest proxy.

Uses the public autocomplete/related endpoint heuristically; for full Trends
data install `pytrends` and swap the implementation (interface stays stable).
"""

from app.datasources.base import BaseHTTPClient
from app.logging_config import get_logger

log = get_logger(__name__)


class TrendsClient(BaseHTTPClient):
    def __init__(self) -> None:
        super().__init__(
            "https://trends.google.com",
            headers={"User-Agent": "Mozilla/5.0 (compatible; polymarket-edge/1.0)"},
        )

    async def interest_hint(self, query: str) -> dict:
        """Best-effort popularity hint. Returns {'query', 'related': [str], 'available': bool}."""
        try:
            resp = await self._client.get(
                "/trends/api/autocomplete/" + query.replace("/", " "), params={"hl": "en-US"}
            )
            if resp.status_code != 200:
                return {"query": query, "related": [], "available": False}
            # Google prefixes JSON with )]}' — strip it.
            text = resp.text.lstrip(")]}'\n")
            import json

            data = json.loads(text)
            topics = (data.get("default") or {}).get("topics") or []
            related = [t.get("title") for t in topics if t.get("title")][:5]
            return {"query": query, "related": related, "available": True}
        except Exception:
            return {"query": query, "related": [], "available": False}
