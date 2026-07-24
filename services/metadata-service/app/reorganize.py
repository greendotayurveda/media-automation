"""
Smart library reorganize CLI (run inside metadata-service for --fetch-metadata).

Dry-run (default):
  python -m app.reorganize

Apply moves + optional OMDb/TMDb enrich:
  python -m app.reorganize --execute --fetch-metadata
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict

from shared.config.settings import settings
from shared.logging.logger import get_logger
from shared.utils.reorganize_library import reorganize_library
from app.metadata import MetadataFetcher

logger = get_logger("reorganize-cli")


async def _enrich(file_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    fetcher = MetadataFetcher()
    return await fetcher.identify_and_store_movie(file_path, context)


async def _run(args: argparse.Namespace) -> int:
    only = [p.strip() for p in (args.only or "").split(",") if p.strip()] or None
    enricher = _enrich if args.fetch_metadata else None

    print(
        f"Library root: {settings.library_root}\n"
        f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}\n"
        f"Fetch metadata: {bool(args.fetch_metadata)}\n"
        f"Limit: {args.limit or 'none'}\n"
        f"Only under: {only or 'all'}\n"
    )

    result = await reorganize_library(
        dry_run=not args.execute,
        fetch_metadata=bool(args.fetch_metadata),
        enricher=enricher,
        limit=args.limit,
        only_under=only,
    )

    summary = {
        "scanned": result.scanned,
        "moved": result.moved,
        "skipped": result.skipped,
        "failed": result.failed,
        "enriched": result.enriched,
    }
    print("Summary:", json.dumps(summary, indent=2))

    if args.verbose:
        for row in result.details:
            print(json.dumps(row, ensure_ascii=False))

    if result.failed:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reorganize library into language/genre folders without the full pipeline."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually move files (default is dry-run).",
    )
    parser.add_argument(
        "--fetch-metadata",
        action="store_true",
        help="Call OMDb/TMDb when language/genres are missing (recommended).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max videos to process.")
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma list of top-level folder names to include, e.g. movies,hollywood",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-file JSON details.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
