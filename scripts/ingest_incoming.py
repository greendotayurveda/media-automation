"""
Scans download_root (and incoming/) recursively and publishes MOVIE_RECEIVED
events for existing video files to trigger the automated pipeline.

Prefer running inside the workflow-engine container (Redis + shared paths):

  docker compose --env-file .env \\
    -f compose/infrastructure.yml -f compose/services.yml \\
    exec workflow-engine python -m app.ingest

Host usage (from repo root, with .env and Redis reachable):

  PYTHONPATH=. python scripts/ingest_incoming.py
"""
import asyncio
import sys
from pathlib import Path

# Allow running as `python scripts/ingest_incoming.py` from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.utils.manual_ingest import ingest_existing_videos  # noqa: E402


if __name__ == "__main__":
    asyncio.run(ingest_existing_videos())
