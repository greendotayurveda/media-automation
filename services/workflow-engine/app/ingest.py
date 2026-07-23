"""
Ingest script to publish MOVIE_RECEIVED events for existing video files.
"""
import asyncio
import uuid
from pathlib import Path

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts"}


async def main():
    publisher = EventPublisher(StreamName.WORKFLOWS)
    downloads_root = settings.download_root

    search_dirs = [
        downloads_root,
        downloads_root / "incoming",
    ]

    files = []
    for d in search_dirs:
        if d.exists():
            for ext in VIDEO_EXTS:
                files.extend(list(d.glob(f"*{ext}")))

    # Deduplicate
    unique = list({str(f): f for f in files}.values())
    print(f"Found {len(unique)} video files to ingest.")

    for file_path in unique:
        if not file_path.is_file():
            continue
        correlation_id = str(uuid.uuid4())
        print(f"Ingesting: {file_path.name}")
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
        await asyncio.sleep(0.2)

    print("✅ Finished publishing ingestion events!")


if __name__ == "__main__":
    asyncio.run(main())
