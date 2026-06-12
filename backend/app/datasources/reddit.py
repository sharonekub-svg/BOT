"""Reddit search via the public JSON endpoint (no OAuth needed for read-only)."""

from dataclasses import dataclass

from app.config import get_settings
from app.datasources.base import BaseHTTPClient


@dataclass
class RedditPost:
    subreddit: str
    title: str
    score: int
    num_comments: int
    url: str | None
    selftext: str


class RedditClient(BaseHTTPClient):
    def __init__(self) -> None:
        super().__init__(
            "https://www.reddit.com",
            headers={"User-Agent": get_settings().reddit_user_agent},
        )

    async def search(self, query: str, limit: int = 10, time_filter: str = "week") -> list[RedditPost]:
        data = await self.get_json(
            "/search.json",
            params={"q": query, "limit": limit, "sort": "relevance", "t": time_filter},
        )
        posts: list[RedditPost] = []
        for child in ((data or {}).get("data") or {}).get("children", [])[:limit]:
            post = child.get("data") or {}
            posts.append(
                RedditPost(
                    subreddit=post.get("subreddit") or "",
                    title=post.get("title") or "",
                    score=int(post.get("score") or 0),
                    num_comments=int(post.get("num_comments") or 0),
                    url=f"https://www.reddit.com{post.get('permalink')}" if post.get("permalink") else None,
                    selftext=(post.get("selftext") or "")[:500],
                )
            )
        return posts
