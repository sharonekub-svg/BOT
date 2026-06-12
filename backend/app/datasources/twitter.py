"""Twitter/X recent search via API v2 (requires a bearer token)."""

from dataclasses import dataclass

from app.config import get_settings
from app.datasources.base import BaseHTTPClient


@dataclass
class Tweet:
    text: str
    like_count: int
    retweet_count: int
    created_at: str | None


class TwitterClient(BaseHTTPClient):
    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            "https://api.twitter.com/2",
            headers={"Authorization": f"Bearer {settings.twitter_bearer_token}"},
        )
        self.enabled = bool(settings.twitter_bearer_token)

    async def recent_search(self, query: str, limit: int = 10) -> list[Tweet]:
        if not self.enabled:
            return []
        data = await self.get_json(
            "/tweets/search/recent",
            params={
                "query": f"{query} -is:retweet lang:en",
                "max_results": max(10, min(limit, 100)),
                "tweet.fields": "public_metrics,created_at",
            },
        )
        tweets: list[Tweet] = []
        for entry in (data or {}).get("data", [])[:limit]:
            metrics = entry.get("public_metrics") or {}
            tweets.append(
                Tweet(
                    text=(entry.get("text") or "")[:400],
                    like_count=int(metrics.get("like_count") or 0),
                    retweet_count=int(metrics.get("retweet_count") or 0),
                    created_at=entry.get("created_at"),
                )
            )
        return tweets
