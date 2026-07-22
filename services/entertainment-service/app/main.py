"""
Main entrypoint for Entertainment (IPTV / Radio / EPG / Recordings).
"""
import asyncio
from datetime import datetime
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.entertainment import EntertainmentManager

logger = get_logger("entertainment-service-main")

app = FastAPI(title="Entertainment Service", version=settings.platform_version)
manager = EntertainmentManager()


class M3UImportRequest(BaseModel):
    m3u_text: Optional[str] = None
    url: Optional[str] = None


class RadioStationRequest(BaseModel):
    name: str
    stream_url: str
    logo_url: Optional[str] = None
    genre: Optional[str] = None
    country: Optional[str] = None
    is_favorite: bool = False


class RecordingRequest(BaseModel):
    title: str
    source_type: str = "iptv"
    source_id: str
    scheduled_start: datetime
    scheduled_end: datetime
    duration_seconds: Optional[int] = None


class EpgRefreshRequest(BaseModel):
    url: Optional[str] = None


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "entertainment-service"}


# ── IPTV ─────────────────────────────────────────────────────

@app.post("/iptv/import")
async def import_iptv(req: M3UImportRequest):
    if not req.m3u_text and not req.url:
        raise HTTPException(status_code=400, detail="m3u_text or url required")
    try:
        return await manager.import_m3u(m3u_text=req.m3u_text, url=req.url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/iptv/channels")
async def list_iptv_channels(
    favorites: bool = False,
    group: Optional[str] = None,
    with_epg: bool = True,
):
    return await manager.list_channels(
        favorites_only=favorites,
        group=group,
        with_epg=with_epg,
    )


@app.get("/iptv/channels/{channel_id}")
async def get_channel(channel_id: str):
    channel = await manager.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@app.get("/iptv/groups")
async def list_groups():
    return {"groups": await manager.list_groups()}


@app.post("/iptv/channels/{channel_id}/favorite")
async def favorite_channel(channel_id: str, favorite: bool = True):
    channel = await manager.favorite_channel(channel_id, favorite=favorite)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


# ── Radio ────────────────────────────────────────────────────

@app.get("/radio/stations")
async def list_radio_stations(favorites: bool = False, genre: Optional[str] = None):
    return await manager.list_stations(favorites_only=favorites, genre=genre)


@app.post("/radio/stations", status_code=201)
async def create_radio_station(req: RadioStationRequest):
    return await manager.create_station(req.model_dump())


@app.post("/radio/stations/{station_id}/favorite")
async def favorite_station(station_id: str, favorite: bool = True):
    station = await manager.favorite_station(station_id, favorite=favorite)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    return station


# ── EPG ──────────────────────────────────────────────────────

@app.post("/epg/refresh")
async def refresh_epg(req: EpgRefreshRequest = EpgRefreshRequest()):
    try:
        return await manager.epg.refresh(url=req.url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/epg/guide")
async def epg_guide(hours: int = Query(6, ge=1, le=48)):
    channels = await manager.list_channels(with_epg=False)
    epg_ids = [c["epg_id"] for c in channels if c.get("epg_id")]
    guide = await manager.epg.guide_for_channels(epg_ids, hours=hours)
    return {
        "channels": channels,
        "guide": guide,
    }


# ── Stream proxy (CORS-safe playback) ────────────────────────

@app.api_route("/stream/iptv/{item_id}", methods=["GET", "HEAD"])
@app.api_route("/stream/radio/{item_id}", methods=["GET", "HEAD"])
async def proxy_stream(item_id: str, request: Request):
    kind = "radio" if "/stream/radio/" in str(request.url.path) else "iptv"
    source = await manager.get_stream_source(kind, item_id)
    if not source:
        raise HTTPException(status_code=404, detail="Stream not found")

    upstream = source["stream_url"]
    # Redirect-style for simple clients; browser players use proxy body
    if request.query_params.get("redirect") == "1":
        from fastapi.responses import RedirectResponse

        return RedirectResponse(upstream, status_code=302)

    headers = {}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=None, follow_redirects=True)
    try:
        req = client.build_request("GET", upstream, headers=headers)
        upstream_resp = await client.send(req, stream=True)
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Upstream stream failed: {exc}") from exc

    if upstream_resp.status_code >= 400:
        await upstream_resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=upstream_resp.status_code, detail="Upstream error")

    media_type = upstream_resp.headers.get("content-type", "application/octet-stream")
    out_headers = {}
    for key in ("content-length", "content-range", "accept-ranges"):
        if key in upstream_resp.headers:
            out_headers[key.title()] = upstream_resp.headers[key]

    async def body():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=upstream_resp.status_code,
        media_type=media_type,
        headers=out_headers,
    )


# ── Recordings ───────────────────────────────────────────────

@app.get("/recordings")
async def list_recordings():
    return await manager.list_recordings()


@app.post("/recordings", status_code=201)
async def schedule_recording(req: RecordingRequest):
    return await manager.schedule_recording(req.model_dump())


# ── Jellyfin export ──────────────────────────────────────────

@app.get("/export/jellyfin.m3u")
async def export_m3u():
    body = await manager.export_m3u()
    return Response(content=body, media_type="audio/x-mpegurl")


@app.get("/export/jellyfin.xmltv")
async def export_xmltv():
    body = await manager.export_xmltv()
    return Response(content=body, media_type="application/xml")


async def _recording_scheduler() -> None:
    logger.info("Recording scheduler started")
    while True:
        try:
            count = await manager.process_due_recordings()
            if count:
                logger.info("Processed due recordings", count=count)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Recording scheduler error", error=str(exc))
        await asyncio.sleep(30)


async def _epg_scheduler() -> None:
    """Refresh EPG periodically when EPG_URL is set."""
    interval = max(3600, int(settings.epg_refresh_hours or 12) * 3600)
    await asyncio.sleep(15)
    while True:
        if settings.epg_url:
            try:
                result = await manager.epg.refresh()
                logger.info("Scheduled EPG refresh ok", programs=result.get("programs"))
            except Exception as exc:
                logger.warning("Scheduled EPG refresh failed", error=str(exc))
        await asyncio.sleep(interval)


async def main():
    scheduler_task = asyncio.create_task(_recording_scheduler())
    epg_task = asyncio.create_task(_epg_scheduler())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8012, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Entertainment Service started")
    await asyncio.gather(scheduler_task, epg_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
