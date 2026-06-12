"""Telegram delivery via the Bot API (plain HTTPS, no extra dependency)."""

import html

import httpx

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


class TelegramAlerter:
    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        settings = get_settings()
        self.token = token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)

    async def send(self, text: str) -> bool:
        if not self.enabled:
            log.debug("telegram disabled; alert suppressed: %s", text[:80])
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code != 200:
                    log.warning("telegram send failed (%s): %s", resp.status_code, resp.text[:200])
                    return False
                return True
        except httpx.HTTPError as exc:
            log.warning("telegram send error: %s", exc)
            return False

    @staticmethod
    def escape(text: str) -> str:
        return html.escape(str(text), quote=False)
