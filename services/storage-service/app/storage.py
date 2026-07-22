"""
Storage monitoring, threshold alerts, and cleanup.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.storage import StorageReport
from shared.logging.logger import get_logger
from shared.utils.file import cleanup_old_files, get_directory_size

logger = get_logger("storage-manager")


class StorageManager:
    """Measures disk usage, persists reports, cleans temp/archives."""

    TRACKED_ROOTS = (
        ("media_root", lambda: settings.media_root),
        ("library_root", lambda: settings.library_root),
        ("download_root", lambda: settings.download_root),
        ("cache_root", lambda: settings.cache_root),
        ("temp_root", lambda: settings.temp_root),
        ("subtitle_root", lambda: settings.subtitle_root),
    )

    async def collect_report(self) -> Dict[str, Any]:
        """Snapshot disk usage and per-directory sizes; persist StorageReport."""
        media_root = settings.media_root
        media_root.mkdir(parents=True, exist_ok=True)

        usage = shutil.disk_usage(media_root)
        breakdown: Dict[str, Any] = {}
        for name, getter in self.TRACKED_ROOTS:
            path = Path(getter())
            size = 0
            if path.exists():
                try:
                    size = get_directory_size(path)
                except Exception as exc:
                    logger.warning("Failed to size directory", path=str(path), error=str(exc))
            breakdown[name] = {
                "path": str(path),
                "size_bytes": size,
                "size_gb": round(size / (1024 ** 3), 2),
            }

        free_gb = usage.free / (1024 ** 3)
        level = "ok"
        if free_gb < settings.storage_critical_threshold_gb:
            level = "critical"
        elif free_gb < settings.storage_warning_threshold_gb:
            level = "warning"

        async with get_db_session() as db:
            report = StorageReport(
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                breakdown=breakdown,
            )
            db.add(report)
            await db.commit()
            await db.refresh(report)
            report_id = report.id

        result = {
            "report_id": report_id,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(free_gb, 2),
            "level": level,
            "warning_threshold_gb": settings.storage_warning_threshold_gb,
            "critical_threshold_gb": settings.storage_critical_threshold_gb,
            "breakdown": breakdown,
        }
        logger.info("Storage report collected", free_gb=result["free_gb"], level=level)
        return result

    async def cleanup(self) -> Dict[str, Any]:
        """
        Remove temp files older than retention days and rejected/replaced
        archives older than archive retention.
        """
        temp_days = settings.storage_temp_retention_days
        archive_days = settings.storage_archive_retention_days

        temp_result = cleanup_old_files(settings.temp_root, temp_days)

        archive_targets = [
            settings.temp_root / "rejected",
            settings.temp_root / "replaced",
            settings.temp_root / "duplicates",
        ]
        archive_deleted_files = 0
        archive_deleted_bytes = 0
        archive_errors = []
        for target in archive_targets:
            if not target.exists():
                continue
            # Archives use longer retention than general temp
            partial = cleanup_old_files(target, archive_days)
            archive_deleted_files += partial["deleted_files"]
            archive_deleted_bytes += partial["deleted_bytes"]
            archive_errors.extend(partial["errors"])

        # Also clean download incoming leftovers older than temp retention
        incoming = settings.download_root / "incoming"
        incoming_result = cleanup_old_files(incoming, temp_days) if incoming.exists() else {
            "deleted_files": 0,
            "deleted_bytes": 0,
            "errors": [],
        }

        result = {
            "temp": temp_result,
            "archives": {
                "deleted_files": archive_deleted_files,
                "deleted_bytes": archive_deleted_bytes,
                "errors": archive_errors,
            },
            "incoming": incoming_result,
            "temp_retention_days": temp_days,
            "archive_retention_days": archive_days,
        }
        logger.info(
            "Storage cleanup complete",
            temp_files=temp_result["deleted_files"],
            archive_files=archive_deleted_files,
        )
        return result

    async def latest_report(self) -> Optional[Dict[str, Any]]:
        async with get_db_session() as db:
            result = await db.execute(
                select(StorageReport).order_by(StorageReport.created_at.desc()).limit(1)
            )
            report = result.scalar_one_or_none()
            if not report:
                return None
            return {
                "report_id": report.id,
                "total_bytes": report.total_bytes,
                "used_bytes": report.used_bytes,
                "free_bytes": report.free_bytes,
                "free_gb": round(report.free_bytes / (1024 ** 3), 2),
                "breakdown": report.breakdown,
                "created_at": report.created_at.isoformat() if report.created_at else None,
            }
