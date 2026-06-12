"""News headlines for AI context. Uses NewsAPI.org when a key is configured."""

from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.core.utils import parse_iso_datetime
from app.datasources.base import BaseHTTPClient
from app.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class Headline:
    source: str
    title: str
    url: str | None
    published_at: datetime | None
    summary: str | None


class NewsClient(BaseHTTPClient):
    def __init__(self) -> None:
        settings = get_settings()
        super().__init__("https://newsapi.org/v2", headers={"X-Api-Key": settings.newsapi_key})
        self.enabled = bool(settings.newsapi_key)

    async def search(self, query: str, limit: int = 10) -> list[Headline]:
        if not self.enabled:
            return []
        data = await self.get_json(
            "/everything",
            params={"q": query, "sortBy": "publishedAt", "pageSize": limit, "language": "en"},
        )
        out: list[Headline] = []
        for article in (data or {}).get("articles", [])[:limit]:
            out.append(
                Headline(
                    source=(article.get("source") or {}).get("name") or "newsapi",
                    title=article.get("title") or "",
                    url=article.get("url"),
                    published_at=parse_iso_datetime(article.get("publishedAt")),
                    summary=article.get("description"),
                )
            )
        return out
