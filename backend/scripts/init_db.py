"""Create all database tables: `python -m scripts.init_db`."""

import asyncio

from app.db.base import init_db
from app.logging_config import get_logger, setup_logging

log = get_logger(__name__)


async def main() -> None:
    setup_logging()
    await init_db()
    log.info("database initialized")


if __name__ == "__main__":
    asyncio.run(main())
