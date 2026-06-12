"""System API: health, status, config summary (no secrets)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import get_settings
from app.core.cache import get_cache
from app.core.utils import now_utc
from app.db import repositories as repo
from app.db.base import get_session
from app.db.models import AIAnalysis, Market, MarketSnapshot, Signal, Trade

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    return {"status": "ok", "ts": now_utc().isoformat(), "version": __version__}


@router.get("/api/v1/status")
async def status(session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    redis_ok = await get_cache().ping()
    return {
        "version": __version__,
        "environment": settings.environment,
        "trading_mode": settings.trading_mode,
        "auto_trade_enabled": settings.auto_trade_enabled,
        "ai_enabled": settings.anthropic_enabled,
        "telegram_enabled": settings.telegram_enabled,
        "redis_connected": redis_ok,
        "counts": {
            "markets": await repo.count_rows(session, Market),
            "snapshots": await repo.count_rows(session, MarketSnapshot),
            "signals": await repo.count_rows(session, Signal),
            "trades": await repo.count_rows(session, Trade),
            "ai_analyses": await repo.count_rows(session, AIAnalysis),
        },
        "ts": now_utc().isoformat(),
    }
