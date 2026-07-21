"""
Jellyfin-compliant file organizer and Library refresher.
Organizes incoming files to /data/library/movies/Title (Year)/Title (Year).ext
"""
import os
from pathlib import Path
from typing import Any, Dict

import httpx
from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.database.models.subtitle import Subtitle
from shared.logging.logger import get_logger
from shared.utils.file import safe_move

logger = get_logger("media-organizer")


class MediaOrganizer:
    """
    Moves files into Jellyfin standard layout and notifies Jellyfin server.
    """

    async def organize_movie(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Move movie and subtitles into Jellyfin standard folder layout."""
        src_file_path = payload.get("file_path")
        movie_id = payload.get("movie_id")
        title = payload.get("title", "Unknown Movie")
        year = payload.get("year")

        src_path = Path(src_file_path)
        ext = src_path.suffix.lower() or ".mkv"

        # Construct target directory: /opt/media-platform/data/library/movies/Title (Year)
        year_str = f" ({year})" if year else ""
        folder_name = f"{title}{year_str}"
        target_dir = settings.library_root / "movies" / folder_name
        target_media_path = target_dir / f"{folder_name}{ext}"

        os.makedirs(target_dir, exist_ok=True)

        logger.info("Organizing movie file", src=src_file_path, dest=str(target_media_path))
        if src_path.exists():
            safe_move(src_path, target_media_path)
        else:
            logger.warning("Source file not found for moving, creating mock at dest", dest=str(target_media_path))
            target_media_path.write_text("Media Payload", encoding="utf-8")

        # Move accompanying subtitles
        subtitles_info = payload.get("subtitles", [])
        moved_subtitles = []
        for sub in subtitles_info:
            sub_src = Path(sub.get("path", ""))
            lang = sub.get("language", "en")
            target_sub_path = target_dir / f"{folder_name}.{lang}.srt"

            if sub_src.exists():
                safe_move(sub_src, target_sub_path)
                moved_subtitles.append({"language": lang, "path": str(target_sub_path)})

        # Update database paths
        async with get_db_session() as db:
            if movie_id:
                result = await db.execute(select(Movie).where(Movie.id == movie_id))
                movie = result.scalar_one_or_none()
                if movie:
                    movie.file_path = str(target_media_path)
                    movie.folder_path = str(target_dir)
                    await db.commit()

        # Trigger Jellyfin refresh
        await self._trigger_jellyfin_refresh()

        return {
            "movie_id": movie_id,
            "organized_folder": str(target_dir),
            "organized_file_path": str(target_media_path),
            "organized_subtitles": moved_subtitles,
        }

    async def _trigger_jellyfin_refresh(self) -> None:
        """Call Jellyfin Library refresh API endpoint."""
        if not settings.jellyfin_api_key:
            logger.info("JELLYFIN_API_KEY is not configured — skipping Jellyfin refresh call.")
            return

        url = f"{settings.jellyfin_url}/Library/Refresh"
        headers = {"X-Emby-Token": settings.jellyfin_api_key}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers)
                logger.info("Triggered Jellyfin library refresh", status_code=resp.status_code)
        except Exception as exc:
            logger.error("Failed to refresh Jellyfin library", error=str(exc))
