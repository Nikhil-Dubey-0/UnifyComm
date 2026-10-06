"""uv run python -m app.worker"""

import asyncio
import contextlib

from app.config import get_settings, setup_process
from app.db import make_engine, make_sessionmaker
from app.worker.loop import build_context, run_forever


async def main() -> None:
    settings = get_settings()
    setup_process(settings)
    engine = make_engine(settings.database_url)
    ctx = build_context(settings, make_sessionmaker(engine))
    stop = asyncio.Event()
    try:
        await run_forever(ctx, stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    # Ctrl+C cancels the main task; the loop's finally blocks clean up.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
