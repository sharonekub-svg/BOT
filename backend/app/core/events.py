"""In-process event bus that mirrors every event to Redis pub/sub.

Workers publish scanner ticks, signals, fills, and alerts here. The API
process subscribes (locally when workers run in-app, via Redis when they run
in a separate container) and fans events out to dashboard WebSocket clients.
"""

import asyncio
from typing import Any, Awaitable, Callable

from app.core.cache import get_cache
from app.core.utils import now_utc
from app.logging_config import get_logger

log = get_logger(__name__)

Subscriber = Callable[[dict], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, handler: Subscriber) -> None:
        self._subscribers.append(handler)

    def unsubscribe(self, handler: Subscriber) -> None:
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    async def publish(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload = {"type": event_type, "ts": now_utc().isoformat(), "data": data or {}}
        for handler in list(self._subscribers):
            try:
                await handler(payload)
            except Exception:  # one bad subscriber must not break the bus
                log.exception("event subscriber failed for %s", event_type)
        # Mirror to Redis so other processes (API <-> worker) see it too.
        asyncio.ensure_future(get_cache().publish(payload))


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
