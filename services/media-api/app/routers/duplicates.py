"""
FastAPI router for Duplicate management (/api/v1/duplicates).
"""
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.connection import get_db
from shared.database.models.duplicate import Duplicate
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher

router = APIRouter(prefix="/api/v1/duplicates", tags=["Duplicates"])
publisher = EventPublisher(StreamName.WORKFLOWS)


class DuplicateResponse(BaseModel):
    id: str
    media_id: str
    media_type: str
    primary_file_path: str
    duplicate_file_path: str
    reason: str
    similarity_score: float
    status: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[DuplicateResponse])
async def list_duplicates(
    status: Optional[str] = "detected",
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Duplicate).order_by(Duplicate.created_at.desc())
    if status:
        stmt = stmt.where(Duplicate.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/scan")
async def trigger_scan():
    """Ask duplicate-service to run a full library scan via its HTTP API."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post("http://duplicate-service:8009/scan")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        # Fallback: publish event for workers that listen
        await publisher.publish(
            event_type=EventType.DUPLICATE_DETECTED,
            payload={"action": "scan_library"},
            source_service="media-api",
        )
        raise HTTPException(status_code=502, detail=f"duplicate-service unavailable: {exc}") from exc


@router.post("/{duplicate_id}/resolve")
async def resolve_duplicate(duplicate_id: str):
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"http://duplicate-service:8009/resolve/{duplicate_id}")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Duplicate not found")
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
