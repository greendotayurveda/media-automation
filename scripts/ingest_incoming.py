"""
Scans download_root/incoming directory and publishes MOVIE_RECEIVED events
for any existing video files to trigger the automated pipeline.
"""
import asyncio
import os
import uuid
from pathlib import Path

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.logging.logger import get_logger

logger = get_logger("ingest-incoming")

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts"}


async def main():
    incoming_dir = settings.download_root / "incoming"
    downloads_dir = settings.download_root

    files = []
    if incoming_dir.exists():
        files.extend([f for f in incoming_dir.glob("*") if f.suffix.lower() in VIDEO_EXTS])
    if downloads_dir.exists():
        files.extend([f for f in downloads_dir.glob("*.mkv") if f.is_file()])

    # Deduplicate
    unique_files = list({str(f): f for f in files}.values())

    if not unique_files:
        print("No video files found in incoming directory.")
        return

    publisher = EventPublisher(StreamName.WORKFLOWS)
    print(f"Found {len(unique_files)} video files to ingest.")

    for file_path in unique_files:
        correlation_id = str(uuid.uuid4())
        print(f"Ingesting: {file_path.name} (Correlation: {correlation_id[:8]})")
        await publisher.publish(
            event_type=EventType.MOVIE_RECEIVED,
            payload={
                "file_path": str(file_path),
                "file_name": file_path.name,
                "file_size": file_path.stat().st_size,
                "source": "manual_ingest",
                "correlation_id": correlation_id,
            },
            source_service="manual-ingest",
            correlation_id=correlation_id,
        )
        await asyncio.sleep(0.5)

    print("✅ All video files published to workflow pipeline!")


if __name__ == "__main__":
    asyncio.run(main())
