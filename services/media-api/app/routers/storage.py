"""
FastAPI router for Storage Reports (/api/v1/storage).
"""
import shutil

import httpx
from fastapi import APIRouter, HTTPException

from shared.config.settings import settings

router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])


@router.get("")
async def get_storage_stats():
    """Get current storage usage metrics (local fallback + storage-service report)."""
    total, used, free = shutil.disk_usage(settings.media_root)
    payload = {
        "media_root": str(settings.media_root),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_gb": round(used / (1024 ** 3), 2),
        "free_gb": round(free / (1024 ** 3), 2),
        "total_gb": round(total / (1024 ** 3), 2),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("http://storage-service:8010/report")
            if resp.status_code == 200:
                payload["report"] = resp.json()
    except Exception:
        pass
    return payload


@router.post("/cleanup")
async def trigger_cleanup():
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post("http://storage-service:8010/cleanup")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
