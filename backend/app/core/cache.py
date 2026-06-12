"""Redis wrapper with graceful degradation.

If Redis is unreachable the platform keeps working: caching becomes a no-op
and pub/sub falls back to the in-process event bus only.
"""

import json
from typing import Any, AsyncIterator

from app.config import get_settings
from app.logging_config import get_logger

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover - redis is in requirements
    aioredis = None

log = get_logger(__name__)

FEED_CHANNEL = "polymarket_edge:feed"


class Cache:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or get_settings().redis_url
        self._client = None
        self._available: bool | None = None

    async def client(self):
        if aioredis is None:
            return None
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def ping(self) -> bool:
        try:
            client = await self.client()
            if client is None:
                self._available = False
                return False
            await client.ping()
            self._available = True
            return True
        except Exception:
            if self._available is not False:
                log.warning("Redis unavailable at %s — running without cache/pubsub bridge", self._url)
            self._available = False
            return False

    async def get_json(self, key: str) -> Any | None:
        if not await self.ping():
            return None
        try:
            raw = await (await self.client()).get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if not await self.ping():
            return
        try:
            await (await self.client()).set(key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception:
            pass

    async def setnx_ttl(self, key: str, ttl_seconds: int) -> bool:
        """Atomic 'set if absent' used for alert cooldowns. True when acquired."""
        if not await self.ping():
            return True  # without redis we don't dedupe across processes
        try:
            return bool(await (await self.client()).set(key, "1", nx=True, ex=ttl_seconds))
        except Exception:
            return True

    async def publish(self, payload: dict, channel: str = FEED_CHANNEL) -> None:
        if not await self.ping():
            return
        try:
            await (await self.client()).publish(channel, json.dumps(payload, default=str))
        except Exception:
            pass

    async def subscribe(self, channel: str = FEED_CHANNEL) -> AsyncIterator[dict]:
        """Yield messages from a Redis channel; ends silently if Redis is down."""
        if not await self.ping():
            return
        client = await self.client()
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    yield json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache
