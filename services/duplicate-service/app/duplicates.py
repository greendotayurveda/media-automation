"""
Duplicate detection and auto-resolution for library media files.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.duplicate import Duplicate
from shared.database.models.movie import Movie
from shared.logging.logger import get_logger
from shared.utils.file import archive_file
from shared.utils.hash import calculate_file_hash

logger = get_logger("duplicate-detector")

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts"}
FILENAME_SIMILARITY_THRESHOLD = 0.92


class DuplicateDetector:
    """
    Scans for duplicate movie files (same movie_id extras, hash collisions,
    near-identical filenames) and auto-resolves by keeping the larger copy.
    """

    async def check_for_movie(self, movie_id: str) -> Dict[str, Any]:
        """Run duplicate checks scoped to a single movie after FILE_ORGANIZED."""
        async with get_db_session() as db:
            result = await db.execute(select(Movie).where(Movie.id == movie_id))
            movie = result.scalar_one_or_none()
            if not movie:
                logger.warning("Movie not found for duplicate check", movie_id=movie_id)
                return {"movie_id": movie_id, "detected": [], "resolved": []}

        detected = await self._find_duplicates_for_movie(movie)
        resolved = []
        for dup in detected:
            resolved_row = await self._auto_resolve(dup)
            if resolved_row:
                resolved.append(resolved_row)

        return {
            "movie_id": movie_id,
            "detected": detected,
            "resolved": resolved,
        }

    async def scan_library(self) -> Dict[str, Any]:
        """Full library scan for hash collisions and multi-file movie folders."""
        async with get_db_session() as db:
            result = await db.execute(
                select(Movie).where(Movie.deleted_at.is_(None))
            )
            movies = list(result.scalars().all())

        all_detected: List[Dict[str, Any]] = []
        all_resolved: List[Dict[str, Any]] = []

        for movie in movies:
            detected = await self._find_duplicates_for_movie(movie)
            all_detected.extend(detected)
            for dup in detected:
                resolved_row = await self._auto_resolve(dup)
                if resolved_row:
                    all_resolved.append(resolved_row)

        hash_dups = await self._scan_hash_collisions()
        all_detected.extend(hash_dups)
        for dup in hash_dups:
            resolved_row = await self._auto_resolve(dup)
            if resolved_row:
                all_resolved.append(resolved_row)

        logger.info(
            "Library duplicate scan complete",
            detected=len(all_detected),
            resolved=len(all_resolved),
        )
        return {"detected": all_detected, "resolved": all_resolved}

    async def resolve_duplicate(self, duplicate_id: str) -> Optional[Dict[str, Any]]:
        """Manually resolve a previously detected Duplicate row."""
        async with get_db_session() as db:
            result = await db.execute(select(Duplicate).where(Duplicate.id == duplicate_id))
            row = result.scalar_one_or_none()
            if not row:
                return None
            if row.status != "detected":
                return self._row_to_dict(row)

        return await self._auto_resolve(self._row_to_dict(row))

    async def _find_duplicates_for_movie(self, movie: Movie) -> List[Dict[str, Any]]:
        """Find extra video files for a movie folder / same movie_id."""
        candidates: List[Path] = []

        if movie.folder_path:
            folder = Path(movie.folder_path)
            if folder.is_dir():
                for path in folder.iterdir():
                    if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                        candidates.append(path)

        if movie.file_path:
            primary = Path(movie.file_path)
            if primary.exists() and primary not in candidates:
                candidates.append(primary)

        if movie.title:
            similar = self._find_similar_filenames(movie.title, movie.year)
            for path in similar:
                if path not in candidates:
                    candidates.append(path)

        if len(candidates) < 2:
            return []

        primary_path = Path(movie.file_path) if movie.file_path else max(
            candidates, key=lambda p: p.stat().st_size if p.exists() else 0
        )
        others = [p for p in candidates if p.resolve() != primary_path.resolve()]
        if not others:
            return []

        detected: List[Dict[str, Any]] = []
        for dup_path in others:
            reason = "same_movie_id"
            score = 1.0
            try:
                if primary_path.exists() and dup_path.exists():
                    if calculate_file_hash(primary_path) == calculate_file_hash(dup_path):
                        reason = "hash_collision"
                        score = 1.0
                    else:
                        score = SequenceMatcher(
                            None, primary_path.name.lower(), dup_path.name.lower()
                        ).ratio()
                        if score >= FILENAME_SIMILARITY_THRESHOLD:
                            reason = "filename_similarity"
                        else:
                            reason = "same_movie_folder"
            except Exception as exc:
                logger.warning("Hash compare failed", error=str(exc), path=str(dup_path))

            keep, discard = self._choose_keep_discard(primary_path, dup_path)
            row = await self._persist_duplicate(
                media_id=movie.id,
                media_type="movie",
                primary_path=keep,
                duplicate_path=discard,
                reason=reason,
                similarity_score=score,
            )
            if row:
                detected.append(row)

        return detected

    async def _scan_hash_collisions(self) -> List[Dict[str, Any]]:
        """Walk library_root and group identical hashes."""
        library = settings.library_root
        if not library.exists():
            return []

        hash_map: Dict[str, List[Path]] = {}
        for path in library.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            try:
                digest = calculate_file_hash(path)
            except Exception:
                continue
            hash_map.setdefault(digest, []).append(path)

        detected: List[Dict[str, Any]] = []
        for paths in hash_map.values():
            if len(paths) < 2:
                continue
            sorted_paths = sorted(
                paths, key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True
            )
            keep = sorted_paths[0]
            media_id = await self._guess_media_id(keep)
            for discard in sorted_paths[1:]:
                row = await self._persist_duplicate(
                    media_id=media_id or "unknown",
                    media_type="movie",
                    primary_path=keep,
                    duplicate_path=discard,
                    reason="hash_collision",
                    similarity_score=1.0,
                )
                if row:
                    detected.append(row)
        return detected

    def _find_similar_filenames(
        self, title: str, year: Optional[int]
    ) -> List[Path]:
        library = settings.library_root / "movies"
        if not library.exists():
            return []

        needle = f"{title} ({year})" if year else title
        needle_lower = needle.lower()
        matches: List[Path] = []
        for path in library.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            ratio = SequenceMatcher(None, needle_lower, path.stem.lower()).ratio()
            if ratio >= FILENAME_SIMILARITY_THRESHOLD:
                matches.append(path)
        return matches

    @staticmethod
    def _choose_keep_discard(a: Path, b: Path) -> Tuple[Path, Path]:
        """Keep the larger file; prefer path under library_root on ties."""
        size_a = a.stat().st_size if a.exists() else 0
        size_b = b.stat().st_size if b.exists() else 0
        if size_a > size_b:
            return a, b
        if size_b > size_a:
            return b, a
        lib = str(settings.library_root)
        if lib in str(a) and lib not in str(b):
            return a, b
        if lib in str(b) and lib not in str(a):
            return b, a
        return a, b

    async def _persist_duplicate(
        self,
        *,
        media_id: str,
        media_type: str,
        primary_path: Path,
        duplicate_path: Path,
        reason: str,
        similarity_score: float,
    ) -> Optional[Dict[str, Any]]:
        primary_size = primary_path.stat().st_size if primary_path.exists() else 0
        dup_size = duplicate_path.stat().st_size if duplicate_path.exists() else 0

        async with get_db_session() as db:
            existing = await db.execute(
                select(Duplicate).where(
                    Duplicate.duplicate_file_path == str(duplicate_path)
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                if row.status != "detected":
                    return None
                row.primary_file_path = str(primary_path)
                row.reason = reason
                row.similarity_score = similarity_score
                row.primary_size_bytes = primary_size
                row.duplicate_size_bytes = dup_size
            else:
                row = Duplicate(
                    media_id=media_id,
                    media_type=media_type,
                    primary_file_path=str(primary_path),
                    duplicate_file_path=str(duplicate_path),
                    reason=reason,
                    similarity_score=similarity_score,
                    primary_size_bytes=primary_size,
                    duplicate_size_bytes=dup_size,
                    status="detected",
                )
                db.add(row)
            await db.commit()
            await db.refresh(row)
            return self._row_to_dict(row)

    async def _auto_resolve(self, dup: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Archive the duplicate file and mark the Duplicate row resolved."""
        dup_path = Path(dup["duplicate_file_path"])
        primary_path = Path(dup["primary_file_path"])

        if not dup_path.exists():
            async with get_db_session() as db:
                result = await db.execute(select(Duplicate).where(Duplicate.id == dup["id"]))
                row = result.scalar_one_or_none()
                if row:
                    row.status = "resolved_keep_primary"
                    await db.commit()
                    await db.refresh(row)
                    return self._row_to_dict(row)
            return None

        try:
            if primary_path.exists() and dup_path.resolve() == primary_path.resolve():
                return None
        except OSError:
            pass

        archive_dir = (
            settings.temp_root
            / "duplicates"
            / datetime.now(timezone.utc).strftime("%Y%m%d")
        )
        os.makedirs(archive_dir, exist_ok=True)
        archived = archive_file(dup_path, archive_dir)

        async with get_db_session() as db:
            result = await db.execute(select(Duplicate).where(Duplicate.id == dup["id"]))
            row = result.scalar_one_or_none()
            if not row:
                return None
            row.status = "resolved_keep_primary"
            await db.commit()
            await db.refresh(row)
            data = self._row_to_dict(row)
            data["archived_path"] = archived
            logger.info(
                "Resolved duplicate",
                duplicate_id=row.id,
                archived=archived,
                kept=row.primary_file_path,
            )
            return data

    async def _guess_media_id(self, path: Path) -> Optional[str]:
        async with get_db_session() as db:
            result = await db.execute(
                select(Movie).where(Movie.file_path == str(path)).limit(1)
            )
            movie = result.scalar_one_or_none()
            return movie.id if movie else None

    @staticmethod
    def _row_to_dict(row: Duplicate) -> Dict[str, Any]:
        return {
            "id": row.id,
            "media_id": row.media_id,
            "media_type": row.media_type,
            "primary_file_path": row.primary_file_path,
            "duplicate_file_path": row.duplicate_file_path,
            "reason": row.reason,
            "similarity_score": row.similarity_score,
            "primary_size_bytes": row.primary_size_bytes,
            "duplicate_size_bytes": row.duplicate_size_bytes,
            "status": row.status,
        }
