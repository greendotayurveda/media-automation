"""
Publish MOVIE_RECEIVED for video files already on disk (manual / recovery ingest).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Iterable, List, Set

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts", ".m4v"}


def collect_video_files(roots: Iterable[Path] | None = None) -> List[Path]:
    """Recursively collect video files under download_root and download_root/incoming."""
    download_root = settings.download_root
    search_roots = list(roots) if roots is not None else [
        download_root / "incoming",
        download_root,
    ]

    found: List[Path] = []
    seen: Set[str] = set()

    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in VIDEO_EXTS:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(path)

    return sorted(found, key=lambda p: str(p).lower())


async def publish_movie_received(files: Iterable[Path], *, delay_seconds: float = 0.2) -> int:
    """Publish one MOVIE_RECEIVED per file. Returns count published."""
    publisher = EventPublisher(StreamName.WORKFLOWS)
    count = 0
    for file_path in files:
        if not file_path.is_file():
            continue
        correlation_id = str(uuid.uuid4())
        print(f"Ingesting: {file_path} ({correlation_id[:8]})")
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
        count += 1
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
    return count


async def ingest_existing_videos(*, delay_seconds: float = 0.2) -> int:
    files = collect_video_files()
    print(f"Found {len(files)} video file(s) to ingest.")
    if not files:
        return 0
    published = await publish_movie_received(files, delay_seconds=delay_seconds)
    print(f"Published {published} MOVIE_RECEIVED event(s).")
    return published
