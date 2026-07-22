"""
Subtitle provider search, download, UTF-8 normalization, and database tracking.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import chardet
from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.subtitle import Subtitle
from shared.logging.logger import get_logger
from app.providers.base import SubtitleCandidate, SubtitleProvider
from app.providers.opensubtitles import OpenSubtitlesProvider
from app.providers.subdl import SubDLProvider

logger = get_logger("subtitle-service")


class SubtitleManager:
    """
    Manages fetching and UTF-8 encoding of missing subtitles.
    Tries OpenSubtitles then SubDL; never writes placeholder tracks.
    """

    def __init__(self) -> None:
        self.desired_languages = settings.subtitle_language_list
        self.providers: List[SubtitleProvider] = [
            OpenSubtitlesProvider(),
            SubDLProvider(),
        ]

    async def fetch_and_normalize_subtitles(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Check for missing subtitles and retrieve them from configured providers."""
        file_path = payload.get("file_path")
        if not file_path:
            return {"subtitles_count": 0, "subtitles": [], "languages_missing": self.desired_languages}

        movie_id = payload.get("movie_id")
        episode_id = payload.get("episode_id")
        title = payload.get("title")
        year = payload.get("year")
        tmdb_id = payload.get("tmdb_id")
        imdb_id = payload.get("imdb_id")
        media_path = Path(file_path)
        file_name = media_path.name

        embedded = {
            str(lang).lower()[:2]
            for lang in (payload.get("embedded_subtitle_languages") or [])
            if lang and str(lang).lower() not in ("und", "unknown")
        }

        downloaded_subtitles: List[Dict[str, Any]] = []
        languages_missing: List[str] = []
        configured = [p for p in self.providers if p.is_configured()]
        if not configured:
            logger.warning(
                "No subtitle providers configured — set OPENSUBTITLES_API_KEY and/or SUBDL_API_KEY"
            )

        for lang in self.desired_languages:
            lang_code = lang.lower().strip()
            if lang_code in embedded:
                logger.info("Skipping language; embedded track present", language=lang_code)
                continue

            srt_filename = f"{media_path.stem}.{lang_code}.srt"
            srt_path = media_path.parent / srt_filename

            if srt_path.exists() and srt_path.stat().st_size > 0:
                logger.info("Subtitle already exists beside media", path=str(srt_path), lang=lang_code)
                self._normalize_utf8(srt_path)
                await self._upsert_subtitle_record(
                    movie_id=movie_id,
                    episode_id=episode_id,
                    language=lang_code,
                    file_path=str(srt_path),
                    provider="local",
                    provider_id=None,
                )
                downloaded_subtitles.append(
                    {"language": lang_code, "path": str(srt_path), "provider": "local"}
                )
                continue

            candidate = await self._search_best_candidate(
                providers=configured,
                language=lang_code,
                title=title,
                year=int(year) if year else None,
                file_path=str(media_path) if media_path.exists() else None,
                file_name=file_name,
                tmdb_id=int(tmdb_id) if tmdb_id else None,
                imdb_id=str(imdb_id) if imdb_id else None,
            )
            if not candidate:
                logger.info("No subtitle found for language", language=lang_code, title=title)
                languages_missing.append(lang_code)
                continue

            provider = next(p for p in configured if p.name == candidate.provider)
            try:
                await provider.download(candidate, srt_path)
                self._normalize_utf8(srt_path)
                await self._upsert_subtitle_record(
                    movie_id=movie_id,
                    episode_id=episode_id,
                    language=lang_code,
                    file_path=str(srt_path),
                    provider=candidate.provider,
                    provider_id=candidate.provider_id,
                    hearing_impaired=candidate.hearing_impaired,
                )
                downloaded_subtitles.append(
                    {
                        "language": lang_code,
                        "path": str(srt_path),
                        "provider": candidate.provider,
                        "release_name": candidate.release_name,
                    }
                )
                logger.info(
                    "Downloaded subtitle",
                    language=lang_code,
                    provider=candidate.provider,
                    path=str(srt_path),
                )
            except Exception as exc:
                logger.error(
                    "Subtitle download failed",
                    language=lang_code,
                    provider=candidate.provider,
                    error=str(exc),
                )
                if srt_path.exists():
                    try:
                        srt_path.unlink()
                    except OSError:
                        pass
                languages_missing.append(lang_code)

        return {
            "subtitles_count": len(downloaded_subtitles),
            "subtitles": downloaded_subtitles,
            "languages_missing": languages_missing,
        }

    async def _search_best_candidate(
        self,
        providers: List[SubtitleProvider],
        language: str,
        **search_kwargs: Any,
    ) -> Optional[SubtitleCandidate]:
        """Query providers in order; return the best scoring hit from the first provider with results."""
        for provider in providers:
            try:
                results = await provider.search(language, **search_kwargs)
            except Exception as exc:
                logger.warning(
                    "Provider search failed",
                    provider=provider.name,
                    language=language,
                    error=str(exc),
                )
                continue
            if results:
                return results[0]
        return None

    def _normalize_utf8(self, srt_path: Path) -> None:
        """Read subtitle file and re-encode to clean UTF-8 if necessary."""
        try:
            raw_bytes = srt_path.read_bytes()
            if not raw_bytes:
                return
            detected = chardet.detect(raw_bytes)
            encoding = detected.get("encoding") or "utf-8"
            if encoding.lower() not in ("utf-8", "ascii", "utf-8-sig"):
                text = raw_bytes.decode(encoding, errors="replace")
                srt_path.write_text(text, encoding="utf-8")
                logger.info(
                    "Normalized subtitle encoding to UTF-8",
                    path=str(srt_path),
                    orig_encoding=encoding,
                )
            elif encoding.lower() == "utf-8-sig":
                text = raw_bytes.decode("utf-8-sig", errors="replace")
                srt_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to normalize subtitle encoding", path=str(srt_path), error=str(exc))

    async def _upsert_subtitle_record(
        self,
        *,
        movie_id: Optional[str],
        episode_id: Optional[str],
        language: str,
        file_path: str,
        provider: str,
        provider_id: Optional[str],
        hearing_impaired: bool = False,
    ) -> None:
        async with get_db_session() as db:
            stmt = select(Subtitle).where(Subtitle.file_path == file_path)
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.provider = provider
                existing.provider_id = provider_id
                existing.language = language
                existing.is_hearing_impaired = hearing_impaired
                existing.movie_id = movie_id or existing.movie_id
                existing.episode_id = episode_id or existing.episode_id
            else:
                db.add(
                    Subtitle(
                        movie_id=movie_id,
                        episode_id=episode_id,
                        language=language,
                        file_path=file_path,
                        provider=provider,
                        provider_id=provider_id,
                        is_hearing_impaired=hearing_impaired,
                        is_synced=True,
                    )
                )
            await db.commit()
