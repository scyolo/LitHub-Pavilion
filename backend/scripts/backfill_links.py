"""Repair real open full-text links; never download PDFs or publish the website."""
import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.services.links_backfill import run_links_backfill
from app.db import get_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only', action='store_true', help='Scan all known publisher/DOI/arXiv evidence, without network requests')
    parser.add_argument('--max-batches', type=int, choices=range(201), metavar='0..200', help='Bound OpenAlex requests to batches of 50 papers (resumes automatically)')
    parser.add_argument('--report', type=Path, help='Write aggregate repair counts as JSON')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    stats = asyncio.run(run_links_backfill(get_session, local_only=args.local_only, max_batches=args.max_batches))
    content = json.dumps(stats, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(content + '\n', encoding='utf-8')
    print(content)


if __name__ == '__main__':
    main()
