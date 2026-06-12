"""WebSocket live feed for the dashboard.

Events arrive from the in-process bus (when workers run in-app) and from the
Redis bridge (when workers run in a separate container), then fan out to every
connected dashboard client.
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.cache import get_cache
from app.core.events import get_event_bus
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []
        self._redis_task: asyncio.Task | None = None
        self._seen_recent: list[str] = []  # dedupe local vs redis copies of one event

    async def start(self) -> None:
        get_event_bus().subscribe(self._on_local_event)
        if self._redis_task is None:
            self._redis_task = asyncio.create_task(self._redis_listener())

    async def stop(self) -> None:
        get_event_bus().unsubscribe(self._on_local_event)
        if self._redis_task is not None:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except (asyncio.CancelledError, Exception):
                pass
            self._redis_task = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, payload: dict) -> None:
        key = f"{payload.get('type')}|{payload.get('ts')}"
        if key in self._seen_recent:
            return
        self._seen_recent.append(key)
        if len(self._seen_recent) > 200:
            self._seen_recent = self._seen_recent[-100:]

        message = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def _on_local_event(self, payload: dict) -> None:
        await self.broadcast(payload)

    async def _redis_listener(self) -> None:
        while True:
            try:
                async for payload in get_cache().subscribe():
                    await self.broadcast(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("redis feed listener error")
            await asyncio.sleep(5)  # redis down — retry quietly


manager = ConnectionManager()


@router.websocket("/ws/feed")
async def feed(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            # Keep the socket alive; clients may send pings we simply echo.
            text = await websocket.receive_text()
            if text == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
