"""
FastAPI router for Storage Reports (/api/v1/storage).
"""
import shutil
from fastapi import APIRouter
from shared.config.settings import settings

router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])


@router.get("")
async def get_storage_stats():
    """Get current storage usage metrics."""
    total, used, free = shutil.disk_usage(settings.media_root)
    return {
        "media_root": str(settings.media_root),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_gb": round(used / (1024 ** 3), 2),
        "free_gb": round(free / (1024 ** 3), 2),
        "total_gb": round(total / (1024 ** 3), 2),
    }
