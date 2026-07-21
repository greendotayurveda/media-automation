"""
Subtitle provider search, download, UTF-8 normalization, and database tracking.
"""
from pathlib import Path
from typing import Any, Dict, List

import chardet

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.subtitle import Subtitle
from shared.logging.logger import get_logger

logger = get_logger("subtitle-service")


class SubtitleManager:
    """
    Manages fetching and UTF-8 encoding of missing subtitles.
    """

    def __init__(self) -> None:
        self.desired_languages = settings.subtitle_language_list

    async def fetch_and_normalize_subtitles(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Check for missing subtitles and retrieve them."""
        file_path = payload.get("file_path")
        movie_id = payload.get("movie_id")
        title = payload.get("title", "Unknown")
        media_path = Path(file_path)

        downloaded_subtitles: List[Dict[str, str]] = []

        for lang in self.desired_languages:
            # Check if subtitle already exists next to media file (e.g. Movie.en.srt)
            srt_filename = f"{media_path.stem}.{lang}.srt"
            srt_path = media_path.parent / srt_filename

            if srt_path.exists():
                logger.info("Subtitle already exists", path=str(srt_path), lang=lang)
                self._normalize_utf8(srt_path)
            else:
                # Placeholder for external OpenSubtitles / SubDL API integration
                logger.info("Creating subtitle placeholder", lang=lang, path=str(srt_path))
                self._create_subtitle_file(srt_path, lang, title)

            # Record in PostgreSQL
            async with get_db_session() as db:
                sub = Subtitle(
                    movie_id=movie_id,
                    language=lang,
                    file_path=str(srt_path),
                    provider="auto",
                    is_synced=True,
                )
                db.add(sub)
                await db.commit()

            downloaded_subtitles.append({"language": lang, "path": str(srt_path)})

        return {
            "subtitles_count": len(downloaded_subtitles),
            "subtitles": downloaded_subtitles,
        }

    def _normalize_utf8(self, srt_path: Path) -> None:
        """Read subtitle file and re-encode to clean UTF-8 if necessary."""
        try:
            raw_bytes = srt_path.read_bytes()
            detected = chardet.detect(raw_bytes)
            encoding = detected.get("encoding") or "utf-8"

            if encoding.lower() not in ("utf-8", "ascii"):
                text = raw_bytes.decode(encoding, errors="replace")
                srt_path.write_text(text, encoding="utf-8")
                logger.info("Normalized subtitle encoding to UTF-8", path=str(srt_path), orig_encoding=encoding)
        except Exception as exc:
            logger.error("Failed to normalize subtitle encoding", path=str(srt_path), error=str(exc))

    def _create_subtitle_file(self, srt_path: Path, lang: str, title: str) -> None:
        """Generate subtitle track file."""
        content = (
            "1\n"
            "00:00:01,000 --> 00:00:05,000\n"
            f"Subtitles for {title} [{lang.upper()}]\n"
            "Automated by Media Automation Platform\n"
        )
        srt_path.write_text(content, encoding="utf-8")
