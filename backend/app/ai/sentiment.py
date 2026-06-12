"""Context assembly for AI analysis: news, Reddit, X, and price history.

Gathers whatever sources are configured, formats compact text blocks for the
prompt, and persists fetched headlines for the news archive.
"""

import asyncio
import re

from app.core.utils import now_utc
from app.datasources.news import Headline, NewsClient
from app.datasources.reddit import RedditClient, RedditPost
from app.datasources.twitter import Tweet, TwitterClient
from app.db.base import session_scope
from app.db.models import NewsItem
from app.logging_config import get_logger

log = get_logger(__name__)

_STOPWORDS = {
    "will", "the", "a", "an", "in", "on", "by", "be", "to", "of", "for", "at",
    "before", "after", "than", "win", "2024", "2025", "2026", "or", "and",
}


def search_query_for(question: str, max_terms: int = 6) -> str:
    """Distill a market question into a short search query."""
    words = re.findall(r"[A-Za-z0-9$#%.']+", question)
    terms = [w for w in words if w.lower() not in _STOPWORDS and len(w) > 2]
    return " ".join(terms[:max_terms]) or question[:60]


def format_news(headlines: list[Headline]) -> str:
    lines = []
    for h in headlines[:10]:
        date = h.published_at.date().isoformat() if h.published_at else "?"
        summary = f" — {h.summary[:120]}" if h.summary else ""
        lines.append(f"- [{date}] ({h.source}) {h.title}{summary}")
    return "\n".join(lines)


def format_reddit(posts: list[RedditPost]) -> str:
    lines = []
    for p in posts[:10]:
        lines.append(f"- r/{p.subreddit} ({p.score} pts, {p.num_comments} comments): {p.title}")
    return "\n".join(lines)


def format_tweets(tweets: list[Tweet]) -> str:
    lines = []
    for t in tweets[:10]:
        lines.append(f"- ({t.like_count} likes, {t.retweet_count} RT): {t.text[:200]}")
    return "\n".join(lines)


def summarize_price_history(points: list[tuple[str, float]]) -> str:
    """`points`: chronological [(iso_ts, yes_price)]. Compact textual summary."""
    if not points:
        return ""
    prices = [p for _, p in points if p is not None]
    if len(prices) < 2:
        return f"current price {prices[0]:.3f}" if prices else ""
    current, first = prices[-1], prices[0]
    hi, lo = max(prices), min(prices)
    change = current - first
    last_moves = ", ".join(f"{p:.2f}" for p in prices[-12:])
    return (
        f"current {current:.3f}; change over window {change:+.3f} "
        f"(from {first:.3f}); range [{lo:.3f}, {hi:.3f}]; last points: {last_moves}"
    )


class ContextGatherer:
    def __init__(
        self,
        news: NewsClient | None = None,
        reddit: RedditClient | None = None,
        twitter: TwitterClient | None = None,
    ) -> None:
        self.news = news or NewsClient()
        self.reddit = reddit or RedditClient()
        self.twitter = twitter or TwitterClient()

    async def gather(self, market_id: str, question: str) -> dict[str, str]:
        """Fetch all sources concurrently; failures degrade to empty blocks."""
        query = search_query_for(question)
        news_task = self.news.search(query)
        reddit_task = self.reddit.search(query)
        twitter_task = self.twitter.recent_search(query)
        headlines, posts, tweets = await asyncio.gather(
            news_task, reddit_task, twitter_task, return_exceptions=True
        )
        if isinstance(headlines, BaseException):
            headlines = []
        if isinstance(posts, BaseException):
            posts = []
        if isinstance(tweets, BaseException):
            tweets = []

        await self._archive_news(market_id, headlines)
        return {
            "news": format_news(headlines),
            "reddit": format_reddit(posts),
            "twitter": format_tweets(tweets),
            "query": query,
        }

    async def _archive_news(self, market_id: str, headlines: list[Headline]) -> None:
        if not headlines:
            return
        try:
            async with session_scope() as session:
                for h in headlines:
                    session.add(
                        NewsItem(
                            source=h.source,
                            title=h.title,
                            url=h.url,
                            published_at=h.published_at,
                            fetched_at=now_utc(),
                            summary=h.summary,
                            matched_market_ids=[market_id],
                        )
                    )
        except Exception:
            log.exception("failed to archive news items")

    async def close(self) -> None:
        await asyncio.gather(
            self.news.close(), self.reddit.close(), self.twitter.close(), return_exceptions=True
        )
