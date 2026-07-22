"""
Library health scanning: missing files, metadata, subtitles.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.health import HealthIssue, HealthReport
from shared.database.models.movie import Movie
from shared.database.models.subtitle import Subtitle
from shared.logging.logger import get_logger

logger = get_logger("health-scanner")


class HealthScanner:
    """Scans movies for integrity / completeness issues."""

    async def run_scan(self, scan_type: str = "scheduled") -> Dict[str, Any]:
        started = time.monotonic()
        issues_payload: List[Dict[str, Any]] = []

        async with get_db_session() as db:
            result = await db.execute(
                select(Movie)
                .where(Movie.deleted_at.is_(None))
                .options(selectinload(Movie.subtitles))
            )
            movies = list(result.scalars().all())

            report = HealthReport(scan_type=scan_type, issues_found=0, issues_resolved=0)
            db.add(report)
            await db.flush()

            for movie in movies:
                found = self._check_movie(movie)
                for issue in found:
                    row = HealthIssue(
                        report_id=report.id,
                        category=issue["category"],
                        severity=issue["severity"],
                        description=issue["description"],
                        file_path=issue.get("file_path"),
                        media_id=movie.id,
                        media_type="movie",
                        is_resolved=False,
                    )
                    db.add(row)
                    issues_payload.append(
                        {
                            "category": issue["category"],
                            "severity": issue["severity"],
                            "description": issue["description"],
                            "file_path": issue.get("file_path"),
                            "media_id": movie.id,
                            "media_type": "movie",
                        }
                    )

            elapsed = int(time.monotonic() - started)
            report.issues_found = len(issues_payload)
            report.execution_time_seconds = elapsed
            await db.commit()
            await db.refresh(report)
            report_id = report.id

        logger.info(
            "Health scan complete",
            report_id=report_id,
            issues=len(issues_payload),
            seconds=int(time.monotonic() - started),
        )
        return {
            "report_id": report_id,
            "scan_type": scan_type,
            "issues_found": len(issues_payload),
            "execution_time_seconds": int(time.monotonic() - started),
            "issues": issues_payload,
        }

    def _check_movie(self, movie: Movie) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # Missing file
        if not movie.file_path:
            issues.append(
                {
                    "category": "missing_file",
                    "severity": "critical",
                    "description": f"Movie '{movie.title}' has no file_path",
                    "file_path": None,
                }
            )
        else:
            path = Path(movie.file_path)
            if not path.exists():
                issues.append(
                    {
                        "category": "missing_file",
                        "severity": "critical",
                        "description": f"File missing for '{movie.title}': {movie.file_path}",
                        "file_path": movie.file_path,
                    }
                )
            else:
                # Optional lightweight ffprobe existence check (skip heavy probe)
                ffprobe = shutil.which("ffprobe")
                if ffprobe and path.stat().st_size == 0:
                    issues.append(
                        {
                            "category": "file_corrupt",
                            "severity": "critical",
                            "description": f"Zero-byte media file for '{movie.title}'",
                            "file_path": movie.file_path,
                        }
                    )

        # Missing metadata
        if movie.tmdb_id is None:
            issues.append(
                {
                    "category": "metadata_missing",
                    "severity": "warning",
                    "description": f"Movie '{movie.title}' has no tmdb_id",
                    "file_path": movie.file_path,
                }
            )

        # Missing subtitles for configured languages
        present_langs = {s.language.lower() for s in (movie.subtitles or [])}
        # Also accept 3-letter / 2-letter variants loosely
        for lang in settings.subtitle_language_list:
            lang_l = lang.lower()
            if lang_l not in present_langs and not any(
                p.startswith(lang_l) or lang_l.startswith(p) for p in present_langs
            ):
                issues.append(
                    {
                        "category": "subtitle_missing",
                        "severity": "info",
                        "description": (
                            f"Movie '{movie.title}' missing subtitle language '{lang}'"
                        ),
                        "file_path": movie.file_path,
                    }
                )

        return issues

    async def list_reports(self, limit: int = 20) -> List[Dict[str, Any]]:
        async with get_db_session() as db:
            result = await db.execute(
                select(HealthReport)
                .order_by(HealthReport.created_at.desc())
                .limit(limit)
            )
            reports = list(result.scalars().all())
            return [
                {
                    "id": r.id,
                    "scan_type": r.scan_type,
                    "issues_found": r.issues_found,
                    "issues_resolved": r.issues_resolved,
                    "execution_time_seconds": r.execution_time_seconds,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in reports
            ]

    async def open_issue_count(self) -> int:
        async with get_db_session() as db:
            result = await db.execute(
                select(HealthIssue).where(HealthIssue.is_resolved.is_(False))
            )
            return len(list(result.scalars().all()))
