"""薄壳：调用链接模式回填服务（逻辑在 app/services/links_backfill.py）。"""
import asyncio
import logging

from app.services.links_backfill import run_links_backfill
from app.db import get_session

logging.basicConfig(level=logging.INFO)


def main() -> None:
    asyncio.run(run_links_backfill(get_session))


if __name__ == "__main__":
    main()
