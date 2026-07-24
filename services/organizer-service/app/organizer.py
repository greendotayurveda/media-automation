"""
Jellyfin-compliant file organizer and Library refresher.
Organizes into library/<language>/<genre>/Title (Year)/Title (Year).ext
Replaces lower-quality library copies on upgrade.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.database.models.subtitle import Subtitle
from shared.logging.logger import get_logger
from shared.utils.file import archive_file, safe_move, safe_replace
from shared.utils.library_category import (
    parse_genre_list,
    resolve_library_relative_path,
    resolve_library_segments,
)

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
        decision = payload.get("decision")
        is_upgrade = decision == "upgrade" or bool(payload.get("upgrade_available"))

        src_path = Path(src_file_path)
        ext = src_path.suffix.lower() or ".mkv"

        year_str = f" ({year})" if year else ""
        folder_name = self._sanitize_folder_name(f"{title}{year_str}")

        original_language = payload.get("original_language")
        genres = payload.get("genres") or payload.get("genre")
        primary_genre = payload.get("primary_genre")
        if movie_id and (not original_language or not genres):
            db_lang, db_genres = await self._load_movie_classify_fields(movie_id)
            original_language = original_language or db_lang
            genres = genres or db_genres

        if not genres and primary_genre:
            genres = [primary_genre]

        relative = resolve_library_relative_path(
            original_language=original_language,
            genres=genres,
            payload=payload,
        )
        lang_folder, genre_folder = resolve_library_segments(
            original_language=original_language,
            genres=genres,
            payload=payload,
        )
        target_dir = settings.library_root / relative / folder_name
        target_media_path = target_dir / f"{folder_name}{ext}"

        os.makedirs(target_dir, exist_ok=True)

        existing_library_path = payload.get("existing_library_path")
        if not existing_library_path and movie_id:
            existing_library_path = await self._load_movie_file_path(movie_id)

        replaced_file_path: Optional[str] = None
        archived_path: Optional[str] = None
        upgrade_applied = False

        logger.info(
            "Organizing movie file",
            src=src_file_path,
            dest=str(target_media_path),
            library_path=str(relative),
            language_folder=lang_folder,
            genre_folder=genre_folder,
            original_language=original_language,
            is_upgrade=is_upgrade,
            existing_library_path=existing_library_path,
        )

        if src_path.exists():
            # Archive previous library copy when upgrading and paths differ.
            if is_upgrade and existing_library_path:
                old_path = Path(existing_library_path)
                if old_path.exists() and old_path.resolve() != target_media_path.resolve():
                    archive_dir = (
                        settings.temp_root
                        / "replaced"
                        / datetime.now(timezone.utc).strftime("%Y%m%d")
                    )
                    archived_path = archive_file(old_path, archive_dir)
                    replaced_file_path = existing_library_path
                    upgrade_applied = True
                    logger.info(
                        "Archived previous library file for upgrade",
                        old=existing_library_path,
                        archived=archived_path,
                    )
                elif old_path.exists() and old_path.resolve() == target_media_path.resolve():
                    # Same destination path — replace in place.
                    replaced_file_path = str(old_path)
                    upgrade_applied = True

            if target_media_path.exists() and (
                not src_path.exists() or src_path.resolve() != target_media_path.resolve()
            ):
                safe_replace(src_path, target_media_path)
                if is_upgrade:
                    upgrade_applied = True
                    replaced_file_path = replaced_file_path or str(target_media_path)
            else:
                safe_move(src_path, target_media_path)
                if is_upgrade and existing_library_path:
                    upgrade_applied = True
        else:
            logger.warning(
                "Source file not found for moving — skipping organize",
                src=src_file_path,
            )
            return {
                "movie_id": movie_id,
                "organized_folder": str(target_dir),
                "organized_file_path": None,
                "organized_subtitles": [],
                "upgrade_applied": False,
                "error": "source_missing",
            }

        # Move accompanying subtitles (replace sidecars on upgrade)
        subtitles_info = payload.get("subtitles", []) or []
        moved_subtitles = await self._organize_subtitles(
            subtitles_info=subtitles_info,
            target_dir=target_dir,
            folder_name=folder_name,
            movie_id=movie_id,
            is_upgrade=is_upgrade,
        )

        # Update database paths
        file_size = target_media_path.stat().st_size if target_media_path.exists() else None
        async with get_db_session() as db:
            if movie_id:
                result = await db.execute(select(Movie).where(Movie.id == movie_id))
                movie = result.scalar_one_or_none()
                if movie:
                    movie.file_path = str(target_media_path)
                    movie.folder_path = str(target_dir)
                    if file_size is not None:
                        movie.file_size_bytes = file_size
                    await db.commit()

        await self._trigger_jellyfin_refresh()

        return {
            "movie_id": movie_id,
            "library_category": lang_folder,
            "library_genre": genre_folder,
            "library_relative_path": str(relative).replace("\\", "/"),
            "original_language": original_language,
            "genres": parse_genre_list(genres),
            "organized_folder": str(target_dir),
            "organized_file_path": str(target_media_path),
            "organized_subtitles": moved_subtitles,
            "upgrade_applied": upgrade_applied,
            "replaced_file_path": replaced_file_path,
            "archived_file_path": archived_path,
            "file_path": str(target_media_path),
            }

    async def _organize_subtitles(
        self,
        *,
        subtitles_info: List[Dict[str, Any]],
        target_dir: Path,
        folder_name: str,
        movie_id: Optional[str],
        is_upgrade: bool,
    ) -> List[Dict[str, str]]:
        moved_subtitles: List[Dict[str, str]] = []
        for sub in subtitles_info:
            sub_src = Path(sub.get("path", ""))
            lang = sub.get("language", "en")
            target_sub_path = target_dir / f"{folder_name}.{lang}.srt"

            if not sub_src.exists():
                continue

            if target_sub_path.exists() and sub_src.resolve() != target_sub_path.resolve():
                if is_upgrade:
                    archive_dir = (
                        settings.temp_root
                        / "replaced"
                        / "subtitles"
                        / datetime.now(timezone.utc).strftime("%Y%m%d")
                    )
                    archive_file(target_sub_path, archive_dir)
                safe_replace(sub_src, target_sub_path)
            else:
                safe_move(sub_src, target_sub_path)

            moved_subtitles.append({"language": lang, "path": str(target_sub_path)})

            if movie_id:
                async with get_db_session() as db:
                    result = await db.execute(
                        select(Subtitle).where(
                            Subtitle.movie_id == movie_id,
                            Subtitle.language == lang,
                        )
                    )
                    rows = list(result.scalars().all())
                    if rows:
                        for row in rows:
                            row.file_path = str(target_sub_path)
                    await db.commit()

        return moved_subtitles

    async def _load_movie_file_path(self, movie_id: str) -> Optional[str]:
        async with get_db_session() as db:
            result = await db.execute(select(Movie).where(Movie.id == movie_id))
            movie = result.scalar_one_or_none()
            if movie and movie.file_path and self._is_library_path(movie.file_path):
                return movie.file_path
        return None

    async def _load_movie_classify_fields(
        self, movie_id: str
    ) -> tuple[Optional[str], List[str]]:
        async with get_db_session() as db:
            result = await db.execute(
                select(Movie)
                .where(Movie.id == movie_id)
                .options(selectinload(Movie.genres))
            )
            movie = result.scalar_one_or_none()
            if not movie:
                return None, []
            genre_names = [g.name for g in (movie.genres or []) if g and g.name]
            return movie.original_language, genre_names

    @staticmethod
    def _is_library_path(path: str) -> bool:
        try:
            resolved = Path(path).resolve()
            library = settings.library_root.resolve()
            return str(resolved).startswith(str(library))
        except (OSError, ValueError):
            return str(settings.library_root) in str(path)

    @staticmethod
    def _sanitize_folder_name(name: str) -> str:
        # Windows-forbidden characters that also cause issues on shared mounts
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, "")
        return name.strip() or "Unknown Movie"

    async def _trigger_jellyfin_refresh(self) -> None:
        """Call Jellyfin Library refresh API endpoint."""
        if not settings.jellyfin_api_key:
            logger.info("JELLYFIN_API_KEY is not configured — skipping Jellyfin refresh call.")
            return

        url = f"{settings.jellyfin_url.rstrip('/')}/Library/Refresh"
        # Support host:port without scheme in env samples
        if not url.startswith("http"):
            url = f"http://{url}"
        headers = {"X-Emby-Token": settings.jellyfin_api_key}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers)
                logger.info("Triggered Jellyfin library refresh", status_code=resp.status_code)
        except Exception as exc:
            logger.error("Failed to refresh Jellyfin library", error=str(exc))
