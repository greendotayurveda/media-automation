"""
Smart library reorganize: move existing movies into
  library/<language>/<genre>/Title (Year)/

Uses DB metadata when present; optionally refreshes via a metadata enricher.
Does NOT run quality/subtitle pipeline (avoids keep_existing traps).
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.logging.logger import get_logger
from shared.utils.library_category import (
    parse_genre_list,
    resolve_library_relative_path,
    resolve_library_segments,
)

logger = get_logger("reorganize-library")

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts", ".m4v", ".m2ts"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
_YEAR_FOLDER_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2})\)\s*$")

EnrichFn = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class ReorganizeResult:
    scanned: int = 0
    moved: int = 0
    skipped: int = 0
    failed: int = 0
    enriched: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)


def _sanitize_folder_name(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "")
    return name.strip() or "Unknown Movie"


def _parse_title_year_from_folder(folder_name: str) -> Tuple[str, Optional[int]]:
    match = _YEAR_FOLDER_RE.match(folder_name.strip())
    if match:
        return match.group("title").strip(), int(match.group("year"))
    return folder_name.strip(), None


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def discover_movie_videos(library_root: Path) -> List[Path]:
    """Find video files under library_root (skips obvious non-movie trees)."""
    skip_roots = {"radio", "live-tv", "recordings", "collections", "tvshows", "tv-shows"}
    found: List[Path] = []
    if not library_root.exists():
        return found

    for path in library_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_EXTS:
            continue
        try:
            rel = path.resolve().relative_to(library_root.resolve())
        except ValueError:
            continue
        if rel.parts and rel.parts[0].lower() in skip_roots:
            continue
        found.append(path)

    return sorted(found, key=lambda p: str(p).lower())


def movie_folder_for_video(video: Path, library_root: Path) -> Path:
    """
    Prefer the Title (Year) directory that contains the video.
    Falls back to the video's parent.
    """
    parent = video.parent
    if _YEAR_FOLDER_RE.match(parent.name):
        return parent
    # Already language/genre/Title — parent is Title folder even without year
    if _is_under(parent, library_root) and parent != library_root:
        return parent
    return parent


def collect_sidecars(video: Path) -> List[Path]:
    """Subtitle / nfo / jpg next to the video sharing the stem prefix."""
    stem = video.stem
    siblings: List[Path] = []
    for sibling in video.parent.iterdir():
        if not sibling.is_file() or sibling == video:
            continue
        name = sibling.name
        if name.startswith(stem) and sibling.suffix.lower() in SUB_EXTS.union(
            {".nfo", ".jpg", ".jpeg", ".png", ".webp"}
        ):
            siblings.append(sibling)
    return siblings


async def _find_movie_record(video: Path, folder: Path) -> Optional[Movie]:
    title_guess, year_guess = _parse_title_year_from_folder(folder.name)
    async with get_db_session() as db:
        # Exact / prefix path match
        result = await db.execute(
            select(Movie)
            .where(
                or_(
                    Movie.file_path == str(video),
                    Movie.folder_path == str(folder),
                    Movie.file_path.ilike(f"%{video.name}"),
                )
            )
            .options(selectinload(Movie.genres))
            .limit(5)
        )
        candidates = list(result.scalars().all())
        for movie in candidates:
            if movie.file_path and Path(movie.file_path).name == video.name:
                return movie
            if movie.folder_path and Path(movie.folder_path).resolve() == folder.resolve():
                return movie

        if title_guess:
            stmt = select(Movie).where(Movie.title.ilike(title_guess)).options(selectinload(Movie.genres))
            if year_guess:
                stmt = stmt.where(Movie.year == year_guess)
            result = await db.execute(stmt.limit(1))
            movie = result.scalar_one_or_none()
            if movie:
                return movie
    return None


def _classify_from_movie(movie: Optional[Movie]) -> Tuple[Optional[str], List[str]]:
    if not movie:
        return None, []
    genres = [g.name for g in (movie.genres or []) if g and g.name]
    return movie.original_language, genres


async def _update_movie_paths(movie_id: str, file_path: str, folder_path: str) -> None:
    async with get_db_session() as db:
        result = await db.execute(select(Movie).where(Movie.id == movie_id))
        movie = result.scalar_one_or_none()
        if not movie:
            return
        movie.file_path = file_path
        movie.folder_path = folder_path
        try:
            movie.file_size_bytes = Path(file_path).stat().st_size
        except OSError:
            pass
        await db.commit()


def _move_path(src: Path, dest: Path, *, dry_run: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return
    if dest.exists():
        if dest.resolve() == src.resolve():
            return
        dest.unlink()
    shutil.move(str(src), str(dest))


def _cleanup_empty_parents(start: Path, stop_at: Path) -> None:
    current = start
    stop_at = stop_at.resolve()
    while True:
        try:
            resolved = current.resolve()
        except OSError:
            break
        if resolved == stop_at or not _is_under(resolved, stop_at):
            break
        try:
            if any(current.iterdir()):
                break
            current.rmdir()
        except OSError:
            break
        current = current.parent


async def reorganize_library(
    *,
    library_root: Optional[Path] = None,
    dry_run: bool = True,
    fetch_metadata: bool = False,
    enricher: Optional[EnrichFn] = None,
    limit: Optional[int] = None,
    only_under: Optional[Sequence[str]] = None,
) -> ReorganizeResult:
    """
    Scan library and move movies into language/genre layout.

    enricher: async (file_path, context) -> metadata dict with original_language/genres/title/year
    """
    root = Path(library_root or settings.library_root)
    result = ReorganizeResult()
    videos = discover_movie_videos(root)

    if only_under:
        allow = {p.lower() for p in only_under}
        videos = [
            v
            for v in videos
            if any(part.lower() in allow for part in v.relative_to(root).parts)
        ]

    if limit is not None:
        videos = videos[: max(0, limit)]

    for video in videos:
        result.scanned += 1
        folder = movie_folder_for_video(video, root)
        detail: Dict[str, Any] = {"src": str(video)}

        try:
            movie = await _find_movie_record(video, folder)
            language, genres = _classify_from_movie(movie)
            title = (movie.title if movie else None) or _parse_title_year_from_folder(folder.name)[0]
            year = (movie.year if movie else None) or _parse_title_year_from_folder(folder.name)[1]

            needs_enrich = fetch_metadata and enricher and (not language or not genres)
            if needs_enrich:
                meta = await enricher(
                    str(video),
                    {
                        "title": title,
                        "year": year,
                        "movie_id": movie.id if movie else None,
                        "file_size_bytes": video.stat().st_size if video.exists() else None,
                    },
                )
                result.enriched += 1
                language = meta.get("original_language") or language
                genres = parse_genre_list(meta.get("genres")) or genres
                title = meta.get("title") or title
                year = meta.get("year") or year
                movie_id = meta.get("movie_id") or (movie.id if movie else None)
                # Reload genres/language from DB if identify stored them
                if movie_id:
                    async with get_db_session() as db:
                        row = await db.execute(
                            select(Movie)
                            .where(Movie.id == movie_id)
                            .options(selectinload(Movie.genres))
                        )
                        refreshed = row.scalar_one_or_none()
                        if refreshed:
                            movie = refreshed
                            language, genres = _classify_from_movie(refreshed)
                            title = refreshed.title or title
                            year = refreshed.year or year
            else:
                movie_id = movie.id if movie else None

            relative = resolve_library_relative_path(
                original_language=language,
                genres=genres,
            )
            lang_folder, genre_folder = resolve_library_segments(
                original_language=language,
                genres=genres,
            )
            year_str = f" ({year})" if year else ""
            dest_folder_name = _sanitize_folder_name(f"{title}{year_str}")
            dest_dir = root / relative / dest_folder_name
            dest_video = dest_dir / f"{dest_folder_name}{video.suffix.lower()}"

            detail.update(
                {
                    "title": title,
                    "year": year,
                    "language": language,
                    "genres": genres,
                    "dest": str(dest_video),
                    "library_path": str(relative).replace("\\", "/"),
                    "language_folder": lang_folder,
                    "genre_folder": genre_folder,
                    "movie_id": movie_id,
                }
            )

            if video.resolve() == dest_video.resolve():
                result.skipped += 1
                detail["status"] = "already_organized"
                result.details.append(detail)
                continue

            # Same logical place (only casing/name tweak on already-correct tree)
            try:
                if (
                    video.parent.resolve() == dest_dir.resolve()
                    and video.name == dest_video.name
                ):
                    result.skipped += 1
                    detail["status"] = "already_organized"
                    result.details.append(detail)
                    continue
            except OSError:
                pass

            sidecars = collect_sidecars(video)
            if not dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)

            _move_path(video, dest_video, dry_run=dry_run)
            moved_subs = []
            for sub in sidecars:
                # Keep language suffix: Title.en.srt → DestFolder.en.srt
                suffix_part = sub.name[len(video.stem) :]  # e.g. .en.srt
                dest_sub = dest_dir / f"{dest_folder_name}{suffix_part}"
                _move_path(sub, dest_sub, dry_run=dry_run)
                moved_subs.append(str(dest_sub))

            if not dry_run:
                _cleanup_empty_parents(folder, root)
                if movie_id:
                    await _update_movie_paths(movie_id, str(dest_video), str(dest_dir))

            result.moved += 1
            detail["status"] = "dry_run_move" if dry_run else "moved"
            detail["sidecars"] = moved_subs
            result.details.append(detail)
            logger.info(
                "Reorganize item",
                status=detail["status"],
                src=str(video),
                dest=str(dest_video),
                library_path=detail["library_path"],
            )
        except Exception as exc:
            result.failed += 1
            detail["status"] = "failed"
            detail["error"] = str(exc)
            result.details.append(detail)
            logger.error("Reorganize failed", src=str(video), error=str(exc))

    return result
