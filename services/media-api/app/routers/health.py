"""
FastAPI router for System Health (/api/v1/health).
"""
import httpx
from fastapi import APIRouter
from shared.database.connection import check_db_connection

router = APIRouter(prefix="/api/v1/health", tags=["Health"])


@router.get("")
async def system_health():
    """Verify platform API, Postgres DB, and health-service open issues."""
    db_healthy = await check_db_connection()
    open_issues = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://health-service:8011/reports")
            if resp.status_code == 200:
                open_issues = resp.json().get("open_issues")
    except Exception:
        pass

    status = "healthy" if db_healthy else "degraded"
    if open_issues and open_issues > 0:
        status = "degraded"

    return {
        "status": status,
        "database": "connected" if db_healthy else "disconnected",
        "open_issues": open_issues if open_issues is not None else 0,
    }


@router.post("/scan")
async def trigger_health_scan():
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post("http://health-service:8011/scan")
        resp.raise_for_status()
        return resp.json()
