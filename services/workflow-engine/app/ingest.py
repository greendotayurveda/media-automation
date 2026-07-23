"""
Ingest script to publish MOVIE_RECEIVED events for existing video files.

Run inside the workflow-engine container:
  docker compose exec workflow-engine python -m app.ingest
"""
import asyncio

from shared.utils.manual_ingest import ingest_existing_videos


if __name__ == "__main__":
    asyncio.run(ingest_existing_videos())
