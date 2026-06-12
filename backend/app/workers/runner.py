"""Standalone worker entrypoint: `python -m app.workers.runner`."""

import asyncio
import signal

from app.config import get_settings
from app.db.base import init_db
from app.logging_config import get_logger, setup_logging
from app.workers.orchestrator import Orchestrator

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    await init_db()

    orchestrator = Orchestrator()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, orchestrator.stop)
        except NotImplementedError:  # pragma: no cover (windows)
            pass
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
