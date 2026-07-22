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
    source: str = "http"
    file_path: Optional[str] = None
    url: Optional[str] = None
    magnet: Optional[str] = None


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
    """Queue HTTP, local, magnet, or .torrent URL download."""
    link = req.magnet or req.url
    if not req.file_path and not link:
        raise HTTPException(status_code=400, detail="file_path, url, or magnet is required")

    is_torrent = bool(req.magnet) or (
        bool(link)
        and (
            link.lower().startswith("magnet:")
            or link.lower().startswith("qbittorrent:")
            or link.lower().endswith(".torrent")
        )
    )
    source = "torrent" if is_torrent else req.source

    download = Download(
        title=req.title,
        source=source,
        status="queued",
        dest_path=req.file_path,
        external_id=link,
    )
    db.add(download)
    await db.commit()
    await db.refresh(download)

    correlation_id = str(uuid.uuid4())
    await publisher.publish(
        event_type=EventType.DOWNLOAD_QUEUED,
        payload={
            "download_id": download.id,
            "file_path": req.file_path,
            "url": link,
            "magnet": req.magnet or (link if link and link.lower().startswith("magnet:") else None),
            "title": req.title,
            "correlation_id": correlation_id,
        },
        source_service="media-api",
        correlation_id=correlation_id,
    )

    return download
