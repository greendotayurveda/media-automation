"""
Quality assessment: score incoming media, persist MediaQuality, compare to library.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.database.models.quality import MediaQuality, QualityRule
from shared.exceptions.base import QualityError
from shared.logging.logger import get_logger

logger = get_logger("quality-assessor")

RESOLUTION_FALLBACK_SCORES = {
    "2160p": 400,
    "1080p": 300,
    "720p": 200,
    "480p": 100,
    "unknown": 0,
}

CODEC_ALIASES = {
    "h265": "hevc",
    "x265": "hevc",
    "h264": "h264",
    "x264": "h264",
    "avc": "h264",
}


class QualityAssessor:
    """
    Evaluates technical quality against preference rules and existing library copies.
    """

    async def check_quality(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score payload specs, store MediaQuality, decide accept / upgrade / keep_existing.
        """
        movie_id = payload.get("movie_id")
        episode_id = payload.get("episode_id")
        if not movie_id and not episode_id:
            raise QualityError("Quality check requires movie_id or episode_id")

        specs = self._extract_specs(payload)
        rule = await self._ensure_default_rule()
        score = self._score(specs, rule)

        async with get_db_session() as db:
            existing = await self._list_existing(db, movie_id=movie_id, episode_id=episode_id)
            existing_best = None
            existing_score = None
            if existing:
                existing_best = max(
                    existing,
                    key=lambda q: self._score(self._quality_to_specs(q), rule),
                )
                existing_score = self._score(self._quality_to_specs(existing_best), rule)

            decision, upgrade_available = self._decide(score, existing_score)

            existing_library_path = payload.get("existing_library_path")
            if movie_id and not existing_library_path:
                movie_result = await db.execute(select(Movie).where(Movie.id == movie_id))
                movie = movie_result.scalar_one_or_none()
                if movie and movie.file_path and self._is_library_path(movie.file_path):
                    existing_library_path = movie.file_path

            quality = MediaQuality(
                movie_id=movie_id,
                episode_id=episode_id,
                resolution=specs["resolution"],
                video_codec=specs["video_codec"],
                bitrate_kbps=specs.get("bitrate_kbps"),
                is_hdr=specs["is_hdr"],
                hdr_format=specs.get("hdr_format"),
                frame_rate=specs.get("frame_rate"),
                audio_codec=specs["audio_codec"],
                audio_channels=specs.get("audio_channels"),
                audio_language=specs.get("audio_language"),
                container=specs.get("container") or "mkv",
            )
            db.add(quality)
            await db.commit()
            await db.refresh(quality)

            result = {
                "quality_id": quality.id,
                "movie_id": movie_id,
                "episode_id": episode_id,
                "file_path": payload.get("file_path"),
                "existing_library_path": existing_library_path,
                "replaced_quality_id": existing_best.id if existing_best and upgrade_available else None,
                "resolution": specs["resolution"],
                "video_codec": specs["video_codec"],
                "audio_codec": specs["audio_codec"],
                "is_hdr": specs["is_hdr"],
                "bitrate_kbps": specs.get("bitrate_kbps"),
                "score": score,
                "existing_score": existing_score,
                "decision": decision,
                "upgrade_available": upgrade_available,
                "rule_name": rule.name,
            }
            logger.info(
                "Quality check complete",
                decision=decision,
                score=score,
                existing_score=existing_score,
                movie_id=movie_id,
            )
            return result

    def _extract_specs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        resolution = str(payload.get("resolution") or "unknown")
        video_codec = self._normalize_codec(str(payload.get("video_codec") or "unknown"))
        audio_codec = str(payload.get("audio_codec") or "unknown")
        channels = payload.get("audio_channels")
        if channels is not None and not isinstance(channels, str):
            channels = self._channels_label(int(channels)) if str(channels).isdigit() else str(channels)

        bitrate = payload.get("bitrate_kbps")
        try:
            bitrate_kbps = int(bitrate) if bitrate is not None else None
        except (TypeError, ValueError):
            bitrate_kbps = None

        return {
            "resolution": resolution,
            "video_codec": video_codec,
            "bitrate_kbps": bitrate_kbps,
            "is_hdr": bool(payload.get("is_hdr", False)),
            "hdr_format": payload.get("hdr_format"),
            "frame_rate": str(payload.get("frame_rate")) if payload.get("frame_rate") else None,
            "audio_codec": audio_codec,
            "audio_channels": channels,
            "audio_language": payload.get("audio_language"),
            "container": str(payload.get("container") or "mkv").split(",")[0],
        }

    @staticmethod
    def _normalize_codec(codec: str) -> str:
        lower = codec.lower().strip()
        return CODEC_ALIASES.get(lower, lower)

    @staticmethod
    def _channels_label(channels: int) -> str:
        mapping = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}
        return mapping.get(channels, str(float(channels)))

    def _score(self, specs: Dict[str, Any], rule: QualityRule) -> float:
        preference = [
            p.strip()
            for p in (rule.resolution_preference or settings.quality_preference).split(",")
            if p.strip()
        ]
        resolution = specs.get("resolution") or "unknown"
        if resolution in preference:
            score = float((len(preference) - preference.index(resolution)) * 100)
        else:
            score = float(RESOLUTION_FALLBACK_SCORES.get(resolution, 0))

        preferred_codecs = [
            self._normalize_codec(c)
            for c in (rule.preferred_codecs or "hevc,h264").split(",")
            if c.strip()
        ]
        video_codec = self._normalize_codec(str(specs.get("video_codec") or "unknown"))
        if video_codec in preferred_codecs:
            score += float((len(preferred_codecs) - preferred_codecs.index(video_codec)) * 20)

        is_hdr = bool(specs.get("is_hdr"))
        if rule.require_hdr and not is_hdr:
            score -= 200
        elif is_hdr and (settings.quality_prefer_hdr or rule.require_hdr):
            score += 50

        if settings.quality_prefer_hevc and video_codec in ("hevc", "av1"):
            score += 30

        bitrate = specs.get("bitrate_kbps") or 0
        score += min(float(bitrate) / 1000.0, 50.0)

        return round(score, 2)

    @staticmethod
    def _decide(score: float, existing_score: Optional[float]) -> Tuple[str, bool]:
        if existing_score is None:
            return "accepted", False
        if score > existing_score:
            return "upgrade", True
        if score < existing_score:
            return "keep_existing", False
        return "accepted", False

    @staticmethod
    def _quality_to_specs(quality: MediaQuality) -> Dict[str, Any]:
        return {
            "resolution": quality.resolution,
            "video_codec": quality.video_codec,
            "bitrate_kbps": quality.bitrate_kbps,
            "is_hdr": quality.is_hdr,
            "audio_codec": quality.audio_codec,
            "audio_channels": quality.audio_channels,
            "container": quality.container,
        }

    async def _list_existing(
        self,
        db,
        movie_id: Optional[str],
        episode_id: Optional[str],
    ) -> List[MediaQuality]:
        stmt = select(MediaQuality)
        if movie_id:
            stmt = stmt.where(MediaQuality.movie_id == movie_id)
        else:
            stmt = stmt.where(MediaQuality.episode_id == episode_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _ensure_default_rule(self) -> QualityRule:
        async with get_db_session() as db:
            result = await db.execute(
                select(QualityRule).where(QualityRule.name == "default").limit(1)
            )
            rule = result.scalar_one_or_none()
            if rule:
                return rule

            rule = QualityRule(
                name="default",
                description="Platform default quality preferences from settings",
                priority=0,
                is_active=True,
                resolution_preference=settings.quality_preference,
                preferred_codecs="hevc,h264" if settings.quality_prefer_hevc else "h264,hevc",
                require_hdr=False,
            )
            db.add(rule)
            await db.commit()
            await db.refresh(rule)
            logger.info("Seeded default quality rule", rule_id=rule.id)
            return rule

    @staticmethod
    def _is_library_path(path: str) -> bool:
        try:
            resolved = Path(path).resolve()
            library = settings.library_root.resolve()
            return str(resolved).startswith(str(library))
        except (OSError, ValueError):
            return str(settings.library_root) in str(path)
