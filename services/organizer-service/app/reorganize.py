"""
Library reorganize CLI (DB + filename only — no OMDb/TMDb).

For metadata refresh use metadata-service:
  docker compose exec metadata-service python -m app.reorganize --execute --fetch-metadata

Dry-run:
  python -m app.reorganize
"""
from __future__ import annotations

import argparse
import asyncio
import json

from shared.config.settings import settings
from shared.utils.reorganize_library import reorganize_library


async def _run(args: argparse.Namespace) -> int:
    only = [p.strip() for p in (args.only or "").split(",") if p.strip()] or None
    print(
        f"Library root: {settings.library_root}\n"
        f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}\n"
        f"Fetch metadata: false (use metadata-service for --fetch-metadata)\n"
        f"Limit: {args.limit or 'none'}\n"
        f"Only under: {only or 'all'}\n"
    )
    result = await reorganize_library(
        dry_run=not args.execute,
        fetch_metadata=False,
        enricher=None,
        limit=args.limit,
        only_under=only,
    )
    print(
        "Summary:",
        json.dumps(
            {
                "scanned": result.scanned,
                "moved": result.moved,
                "skipped": result.skipped,
                "failed": result.failed,
                "enriched": result.enriched,
            },
            indent=2,
        ),
    )
    if args.verbose:
        for row in result.details:
            print(json.dumps(row, ensure_ascii=False))
    return 1 if result.failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Reorganize library (no metadata fetch).")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", type=str, default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
