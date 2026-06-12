"""Claude analysis engine.

Calls the Anthropic API (AsyncAnthropic) with:
- a cached, stable system prompt (`cache_control: ephemeral`),
- adaptive thinking for reasoning quality,
- structured JSON output enforced via `output_config.format`.
"""

import asyncio
import json

from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.schemas import ANALYSIS_JSON_SCHEMA, MarketAnalysis
from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)

try:
    import anthropic
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover — anthropic is in requirements
    anthropic = None
    AsyncAnthropic = None


class ClaudeEngine:
    """Thin, rate-limited wrapper around the Messages API for market analysis."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.enabled = self.settings.anthropic_enabled and AsyncAnthropic is not None
        self._client: AsyncAnthropic | None = None
        self._semaphore = asyncio.Semaphore(max(1, self.settings.ai_max_concurrency))

    @property
    def client(self) -> "AsyncAnthropic":
        if self._client is None:
            self._client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    async def analyze_market(
        self,
        question: str,
        description: str | None,
        category: str | None,
        end_date_iso: str | None,
        implied_prob: float | None,
        price_history_summary: str,
        news_block: str = "",
        reddit_block: str = "",
        twitter_block: str = "",
        extra_context: str = "",
    ) -> tuple[MarketAnalysis, dict] | None:
        """Returns (analysis, usage) or None when disabled/refused/failed."""
        if not self.enabled:
            return None

        user_prompt = build_user_prompt(
            question=question,
            description=description,
            category=category,
            end_date_iso=end_date_iso,
            implied_prob=implied_prob,
            price_history_summary=price_history_summary,
            news_block=news_block,
            reddit_block=reddit_block,
            twitter_block=twitter_block,
            extra_context=extra_context,
        )

        async with self._semaphore:
            try:
                response = await self.client.messages.create(
                    model=self.settings.anthropic_model,
                    max_tokens=16000,
                    thinking={"type": "adaptive"},
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_prompt}],
                    output_config={
                        "format": {"type": "json_schema", "schema": ANALYSIS_JSON_SCHEMA}
                    },
                )
            except anthropic.RateLimitError:
                log.warning("Anthropic rate limited; skipping analysis for: %s", question[:60])
                return None
            except anthropic.APIStatusError as exc:
                log.error("Anthropic API error %s: %s", exc.status_code, exc.message)
                return None
            except anthropic.APIConnectionError:
                log.error("Anthropic connection error; skipping analysis")
                return None

        if response.stop_reason == "refusal":
            log.warning("analysis refused for market: %s", question[:60])
            return None

        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return None
        try:
            analysis = MarketAnalysis.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            log.error("failed to parse analysis JSON: %s", exc)
            return None

        usage = {
            "input_tokens": getattr(response.usage, "input_tokens", None),
            "output_tokens": getattr(response.usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", None),
            "model": self.settings.anthropic_model,
        }
        return analysis, usage


_engine: ClaudeEngine | None = None


def get_claude_engine() -> ClaudeEngine:
    global _engine
    if _engine is None:
        _engine = ClaudeEngine()
    return _engine
