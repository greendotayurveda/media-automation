"""
HTTP / local-path / qBittorrent download handler.
"""
from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.download import Download
from shared.exceptions.base import DownloadError, DownloadTimeoutError
from shared.logging.logger import get_logger
from app.qbittorrent import (
    DONE_STATES,
    FAIL_STATES,
    QBittorrentClient,
    is_torrent_link,
    normalize_qbittorrent_url,
)

logger = get_logger("downloader")


class Downloader:
    """
    Processes DOWNLOAD_QUEUED jobs: HTTP, local intake, or qBittorrent magnets/torrents.
    """

    def __init__(self) -> None:
        self.downloads_bus = EventPublisher(StreamName.DOWNLOADS)

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        download_id = payload.get("download_id")
        url = payload.get("url") or payload.get("source_url") or payload.get("magnet")
        file_path = payload.get("file_path") or payload.get("dest_path")
        torrent_file = payload.get("torrent_file")
        title = payload.get("title") or "download"

        download = await self._load_or_create(download_id, title, file_path, url, torrent_file)
        download_id = download["id"]

        await self._update(download_id, status="downloading", progress=0.0)

        try:
            if torrent_file and Path(torrent_file).exists():
                dest = await self._download_torrent(download_id, url=None, torrent_file=Path(torrent_file), title=title, payload=payload)
            elif url and is_torrent_link(url):
                dest = await self._download_torrent(download_id, url=url, torrent_file=None, title=title, payload=payload)
            elif url and self._is_http_url(url) and url.lower().endswith(".torrent"):
                dest = await self._download_torrent(download_id, url=url, torrent_file=None, title=title, payload=payload)
            elif url and self._is_http_url(url):
                dest = await self._download_http(download_id, url, title)
            elif file_path and Path(file_path).exists():
                dest = await self._intake_local(download_id, Path(file_path), title)
            elif file_path and self._is_http_url(file_path):
                dest = await self._download_http(download_id, file_path, title)
            else:
                raise DownloadError(
                    "No valid url, magnet, torrent file, or existing file_path for download",
                    download_id=download_id,
                    url=url,
                    file_path=file_path,
                )

            size = Path(dest).stat().st_size if Path(dest).exists() else None
            await self._update(
                download_id,
                status="completed",
                progress=100.0,
                dest_path=dest,
                temp_path=dest,
                file_size_bytes=size,
                error_message=None,
            )
            logger.info("Download completed", download_id=download_id, dest=dest)
            return {
                "download_id": download_id,
                "title": title,
                "status": "completed",
                "dest_path": dest,
                "file_path": dest,
                "file_size_bytes": size,
                "source": "torrent" if (url and is_torrent_link(url)) or torrent_file else "http",
            }
        except Exception as exc:
            await self._update(
                download_id,
                status="failed",
                error_message=str(exc),
            )
            logger.error("Download failed", download_id=download_id, error=str(exc))
            raise

    async def _download_torrent(
        self,
        download_id: str,
        *,
        url: Optional[str],
        torrent_file: Optional[Path],
        title: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        client = QBittorrentClient()
        if not client.is_configured:
            raise DownloadError(
                "qBittorrent is not configured — set QBITTORRENT_URL and QBITTORRENT_PASSWORD"
            )

        Path(settings.qbittorrent_save_path).mkdir(parents=True, exist_ok=True)
        tag = f"mp-{download_id[:8]}"

        async with client:
            if torrent_file:
                info_hash = await client.add_torrent_file(torrent_file, tag=tag)
            else:
                assert url
                info_hash = await client.add_magnet_or_url(
                    normalize_qbittorrent_url(url),
                    tag=tag,
                )

            await self._update(download_id, external_id=info_hash, source="torrent")

            poll = max(5, int(settings.qbittorrent_poll_interval_seconds))
            deadline = time.monotonic() + int(settings.qbittorrent_timeout_seconds)

            consecutive_fails = 0
            while True:
                if time.monotonic() > deadline:
                    raise DownloadTimeoutError(
                        f"Torrent timed out after {settings.qbittorrent_timeout_seconds}s",
                        hash=info_hash,
                    )

                torrent = await client.get_torrent(info_hash)
                if not torrent:
                    await asyncio.sleep(poll)
                    continue

                state = torrent.get("state") or ""
                progress = float(torrent.get("progress") or 0.0) * 100.0
                dlspeed = int(torrent.get("dlspeed") or 0)
                eta = torrent.get("eta")
                name = torrent.get("name") or title
                eta_seconds = None
                if eta is not None:
                    try:
                        val = int(eta)
                        if 0 <= val <= 2147483647 and val != 8640000:
                            eta_seconds = val
                    except (ValueError, TypeError):
                        pass

                await self._update(
                    download_id,
                    progress=round(min(progress, 99.5), 2),
                    download_speed_bps=dlspeed,
                    eta_seconds=eta_seconds,
                    title=name[:500],
                )

                if payload:
                    try:
                        await self.downloads_bus.publish(
                            event_type=EventType.DOWNLOAD_PROGRESS,
                            payload={
                                **payload,
                                "download_id": download_id,
                                "progress": round(min(progress, 99.5), 1),
                                "download_speed_bps": dlspeed,
                                "eta_seconds": eta_seconds,
                                "title": name[:500],
                                "state": state,
                            },
                            source_service="download-service",
                            correlation_id=payload.get("correlation_id"),
                        )
                    except Exception:
                        pass

                if state in FAIL_STATES:
                    consecutive_fails += 1
                    logger.warning("qBittorrent reported transient fail state, attempting auto-resume...", state=state, fails=consecutive_fails)
                    try:
                        await client.resume_torrent(info_hash)
                    except Exception:
                        pass
                    if consecutive_fails >= 10:
                        raise DownloadError(
                            f"qBittorrent torrent failed with state={state}",
                            hash=info_hash,
                        )
                else:
                    consecutive_fails = 0

                completed = progress >= 99.9 or state in DONE_STATES or int(torrent.get("amount_left") or 1) == 0
                if completed:
                    content_path = torrent.get("content_path") or torrent.get("save_path") or settings.qbittorrent_save_path
                    video = await client.pick_primary_video(info_hash, content_path)
                    if not video or not video.exists():
                        raise DownloadError(
                            "Torrent finished but no video file was found",
                            hash=info_hash,
                            content_path=content_path,
                        )
                    return await self._stage_completed_video(download_id, video)

                await asyncio.sleep(poll)

    async def _stage_completed_video(self, download_id: str, src: Path) -> str:
        """
        Copy completed video into download_root/incoming so the pipeline has a stable path.
        Leaves the original in the qBittorrent save folder.
        """
        incoming = settings.download_root / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        dest = incoming / src.name
        if dest.exists() and dest.resolve() != src.resolve():
            stem, suffix = dest.stem, dest.suffix
            idx = 1
            while dest.exists():
                dest = incoming / f"{stem}_{idx}{suffix}"
                idx += 1

        if dest.resolve() != src.resolve():
            logger.info("Staging torrent video into incoming", src=str(src), dest=str(dest))
            shutil.copy2(str(src), str(dest))
        await self._update(download_id, progress=99.5, dest_path=str(dest))
        return str(dest)

    async def _download_http(self, download_id: str, url: str, title: str) -> str:
        incoming = settings.download_root / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)

        filename = self._filename_from_url(url, title)
        dest = incoming / filename
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            idx = 1
            while dest.exists():
                dest = incoming / f"{stem}_{idx}{suffix}"
                idx += 1

        logger.info("Starting HTTP download", url=url, dest=str(dest))
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                written = 0
                with open(dest, "wb") as out:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                        out.write(chunk)
                        written += len(chunk)
                        if total > 0:
                            progress = min(99.0, (written / total) * 100.0)
                            await self._update(
                                download_id,
                                progress=round(progress, 2),
                                file_size_bytes=total,
                                download_speed_bps=0,
                            )

        await self._update(download_id, progress=99.0, dest_path=str(dest))
        return str(dest)

    async def _intake_local(self, download_id: str, src: Path, title: str) -> str:
        incoming = settings.download_root / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)

        try:
            src_resolved = src.resolve()
            incoming_resolved = incoming.resolve()
            if str(src_resolved).startswith(str(incoming_resolved)):
                await self._update(download_id, progress=50.0, dest_path=str(src))
                return str(src)
        except OSError:
            pass

        dest = incoming / src.name
        if dest.exists() and dest.resolve() != src.resolve():
            stem, suffix = dest.stem, dest.suffix
            idx = 1
            while dest.exists():
                dest = incoming / f"{stem}_{idx}{suffix}"
                idx += 1

        logger.info("Intaking local file", src=str(src), dest=str(dest))
        shutil.copy2(str(src), str(dest))
        await self._update(download_id, progress=80.0, dest_path=str(dest))
        return str(dest)

    async def _load_or_create(
        self,
        download_id: Optional[str],
        title: str,
        file_path: Optional[str],
        url: Optional[str],
        torrent_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_db_session() as db:
            if download_id:
                result = await db.execute(select(Download).where(Download.id == download_id))
                row = result.scalar_one_or_none()
                if row:
                    return {"id": row.id, "title": row.title, "status": row.status}

            source = "local"
            if torrent_file or (url and is_torrent_link(url)):
                source = "torrent"
            elif url:
                source = "http"

            ext_id = (url or torrent_file)
            if ext_id and len(ext_id) > 255:
                ext_id = ext_id[:255]

            row = Download(
                title=title,
                source=source,
                status="queued",
                dest_path=file_path,
                external_id=ext_id,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return {"id": row.id, "title": row.title, "status": row.status}

    async def _update(self, download_id: str, **fields: Any) -> None:
        async with get_db_session() as db:
            result = await db.execute(select(Download).where(Download.id == download_id))
            row = result.scalar_one_or_none()
            if not row:
                return
            for key, value in fields.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            await db.commit()

    @staticmethod
    def _is_http_url(value: str) -> bool:
        return value.startswith("http://") or value.startswith("https://")

    @staticmethod
    def _filename_from_url(url: str, title: str) -> str:
        parsed = urlparse(url)
        name = unquote(Path(parsed.path).name)
        if name and "." in name:
            return name
        safe = "".join(c if c.isalnum() or c in " ._-" else "_" for c in title).strip()
        return f"{safe or 'download'}.mkv"
