"""
FastAPI router for Download management endpoints (/api/v1/downloads).
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.connection import get_db
from shared.database.models.download import Download
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher

router = APIRouter(prefix="/api/v1/downloads", tags=["Downloads"])
publisher = EventPublisher(StreamName.DOWNLOADS)


class CreateDownloadRequest(BaseModel):
    title: str
    source: str = "telegram"
    file_path: str


class DownloadResponse(BaseModel):
    id: str
    title: str
    source: str
    status: str
    progress: float
    file_size_bytes: Optional[int] = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[DownloadResponse])
async def list_downloads(db: AsyncSession = Depends(get_db)):
    """List active downloads."""
    result = await db.execute(select(Download).order_by(Download.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=DownloadResponse, status_code=201)
async def create_download(req: CreateDownloadRequest, db: AsyncSession = Depends(get_db)):
    """Queue a new download manually via API."""
    download = Download(
        title=req.title,
        source=req.source,
        status="queued",
        dest_path=req.file_path,
    )
    db.add(download)
    await db.commit()
    await db.refresh(download)

    # Publish event to trigger workflow engine
    correlation_id = str(uuid.uuid4())
    await publisher.publish(
        event_type=EventType.DOWNLOAD_QUEUED,
        payload={"download_id": download.id, "file_path": req.file_path},
        source_service="media-api",
        correlation_id=correlation_id,
    )

    return download
