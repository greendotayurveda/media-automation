"""
FastAPI router for System Health (/api/v1/health).
"""
from fastapi import APIRouter
from shared.database.connection import check_db_connection

router = APIRouter(prefix="/api/v1/health", tags=["Health"])


@router.get("")
async def system_health():
    """Verify platform API, Postgres DB, and dependencies health status."""
    db_healthy = await check_db_connection()
    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
    }
