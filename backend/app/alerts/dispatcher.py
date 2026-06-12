"""Alert rules + cooldown/dedup. All thresholds come from config.

Rules:
- high_edge       — signal with edge score above EDGE_ALERT_THRESHOLD
- arbitrage       — new arb with net edge above ARB_ALERT_MIN_EDGE
- big_move        — market moved more than BIG_MOVE_ALERT_PCT points in 24h
- ai_conviction   — AI confidence above AI_MIN_CONFIDENCE_ALERT with non-neutral signal
- risk            — risk-manager warnings (daily loss, drawdown, exposure)
"""

from app.alerts.telegram import TelegramAlerter
from app.config import get_settings
from app.core.cache import get_cache
from app.logging_config import get_logger

log = get_logger(__name__)


class AlertDispatcher:
    def __init__(self, alerter: TelegramAlerter | None = None) -> None:
        self.settings = get_settings()
        self.alerter = alerter or TelegramAlerter()
        self._local_sent: set[str] = set()  # fallback dedup when Redis is down

    async def _should_send(self, key: str) -> bool:
        cooldown = self.settings.alert_cooldown_minutes * 60
        acquired = await get_cache().setnx_ttl(f"alert:{key}", cooldown)
        if not acquired:
            return False
        if key in self._local_sent:
            return False
        self._local_sent.add(key)
        if len(self._local_sent) > 5000:
            self._local_sent.clear()
        return True

    # ------------------------------------------------------------ rules

    async def high_edge(self, market_question: str, market_id: str, edge_score: float,
                        direction: str, ev: float, fair: float, implied: float) -> None:
        if edge_score < self.settings.edge_alert_threshold:
            return
        if not await self._should_send(f"edge:{market_id}:{direction}"):
            return
        esc = self.alerter.escape
        await self.alerter.send(
            "🎯 <b>High-edge opportunity</b>\n"
            f"{esc(market_question)}\n"
            f"Edge score: <b>{edge_score:.0f}/100</b> | {esc(direction)}\n"
            f"Implied {implied:.2f} → fair {fair:.2f} | EV {ev * 100:+.1f}%"
        )

    async def arbitrage(self, kind: str, description: str, net_edge: float, market_ids: list[str]) -> None:
        if net_edge < self.settings.arb_alert_min_edge:
            return
        if not await self._should_send(f"arb:{kind}:{','.join(sorted(market_ids))[:80]}"):
            return
        esc = self.alerter.escape
        await self.alerter.send(
            "♻️ <b>Arbitrage detected</b>\n"
            f"Type: {esc(kind)}\n{esc(description)}\n"
            f"Net edge: <b>{net_edge * 100:.2f}%</b> per $1 basket"
        )

    async def big_move(self, market_question: str, market_id: str, change_points: float, price: float) -> None:
        if abs(change_points) * 100 < self.settings.big_move_alert_pct:
            return
        if not await self._should_send(f"move:{market_id}"):
            return
        esc = self.alerter.escape
        arrow = "📈" if change_points > 0 else "📉"
        await self.alerter.send(
            f"{arrow} <b>Large market move</b>\n"
            f"{esc(market_question)}\n"
            f"24h change: <b>{change_points * 100:+.1f}pts</b> → now {price:.2f}"
        )

    async def ai_conviction(self, market_question: str, market_id: str, signal: str,
                            confidence: float, prob: float, implied: float, reasoning: str) -> None:
        if confidence < self.settings.ai_min_confidence_alert or signal == "neutral":
            return
        if not await self._should_send(f"ai:{market_id}:{signal}"):
            return
        esc = self.alerter.escape
        emoji = "🐂" if signal == "bullish" else "🐻"
        await self.alerter.send(
            f"{emoji} <b>AI conviction: {esc(signal)}</b>\n"
            f"{esc(market_question)}\n"
            f"AI prob {prob:.2f} vs market {implied:.2f} (confidence {confidence:.0%})\n"
            f"<i>{esc(reasoning[:300])}</i>"
        )

    async def risk_warning(self, warnings: list[str]) -> None:
        if not warnings:
            return
        if not await self._should_send("risk:" + "|".join(sorted(warnings))[:100]):
            return
        esc = self.alerter.escape
        body = "\n".join(f"• {esc(w)}" for w in warnings)
        await self.alerter.send(f"⚠️ <b>Risk warning</b>\n{body}")
