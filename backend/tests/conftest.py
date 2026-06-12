"""Test configuration: in-memory SQLite, no external services, no workers."""

import os

# Must run before any app import so Settings picks the test database.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")  # intentionally unreachable
os.environ.setdefault("RUN_WORKERS_IN_APP", "false")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")

import pytest  # noqa: E402

from app.db.base import dispose_engine, get_sessionmaker, init_db  # noqa: E402


@pytest.fixture
async def db():
    """Fresh schema per test (in-memory SQLite lives for the engine's lifetime)."""
    await init_db()
    yield
    await dispose_engine()


@pytest.fixture
async def session(db):
    async with get_sessionmaker()() as session:
        yield session
        await session.commit()
