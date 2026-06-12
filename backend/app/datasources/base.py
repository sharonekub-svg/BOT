"""Shared async HTTP client with retries and backoff for all data sources."""

import asyncio
from typing import Any

import httpx

from app.logging_config import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class BaseHTTPClient:
    def __init__(self, base_url: str, headers: dict | None = None, max_retries: int = 3) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self.base_url, headers=headers or {}, timeout=DEFAULT_TIMEOUT
        )

    async def get_json(self, path: str, params: dict | None = None) -> Any | None:
        """GET with exponential backoff. Returns parsed JSON or None on failure."""
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.get(path, params=params)
                if resp.status_code in RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                if attempt >= self.max_retries:
                    log.warning("GET %s%s failed after %d attempts: %s", self.base_url, path, attempt + 1, exc)
                    return None
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
        return None

    async def post_json(self, path: str, json_body: Any) -> Any | None:
        try:
            resp = await self._client.post(path, json=json_body)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            log.warning("POST %s%s failed: %s", self.base_url, path, exc)
            return None

    async def close(self) -> None:
        await self._client.aclose()
