"""
IPTV / Radio / Recording / export domain logic.
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

import httpx
from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.entertainment import IptvChannel, RadioStation, Recording
from shared.logging.logger import get_logger
from app.epg import EpgManager

logger = get_logger("entertainment")

EXTINF_RE = __import__("re").compile(
    r"#EXTINF:(?P<duration>-?\d+)(?:\s+(?P<attrs>.*?))?,\s*(?P<name>.*)",
    __import__("re").IGNORECASE,
)
ATTR_RE = __import__("re").compile(r'([\w-]+)="([^"]*)"')


class EntertainmentManager:
    """CRUD, M3U import, recordings, Jellyfin export helpers."""

    def __init__(self) -> None:
        self.epg = EpgManager()

    async def import_m3u(
        self,
        *,
        m3u_text: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Dict[str, Any]:
        if url and not m3u_text:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                m3u_text = resp.text

        if not m3u_text:
            raise ValueError("Provide m3u_text or url")

        channels = self._parse_m3u(m3u_text)
        created = 0
        updated = 0

        async with get_db_session() as db:
            for ch in channels:
                result = await db.execute(
                    select(IptvChannel).where(IptvChannel.stream_url == ch["stream_url"])
                )
                existing = result.scalar_one_or_none()
                if existing:
                    existing.name = ch["name"]
                    existing.logo_url = ch.get("logo_url")
                    existing.group_name = ch.get("group_name")
                    existing.epg_id = ch.get("epg_id")
                    existing.is_active = True
                    updated += 1
                else:
                    db.add(
                        IptvChannel(
                            name=ch["name"],
                            stream_url=ch["stream_url"],
                            logo_url=ch.get("logo_url"),
                            group_name=ch.get("group_name"),
                            epg_id=ch.get("epg_id"),
                        )
                    )
                    created += 1
            await db.commit()

        logger.info("M3U import complete", created=created, updated=updated)
        return {"created": created, "updated": updated, "total_parsed": len(channels)}

    @staticmethod
    def _parse_m3u(text: str) -> List[Dict[str, Any]]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        channels: List[Dict[str, Any]] = []
        pending: Optional[Dict[str, Any]] = None

        for line in lines:
            if line.startswith("#EXTINF"):
                match = EXTINF_RE.match(line)
                name = "Unknown"
                attrs: Dict[str, str] = {}
                if match:
                    name = match.group("name").strip() or "Unknown"
                    raw_attrs = match.group("attrs") or ""
                    attrs = dict(ATTR_RE.findall(raw_attrs))
                pending = {
                    "name": name,
                    "logo_url": attrs.get("tvg-logo"),
                    "group_name": attrs.get("group-title"),
                    "epg_id": attrs.get("tvg-id"),
                }
            elif line.startswith("#"):
                continue
            elif pending is not None:
                pending["stream_url"] = line
                channels.append(pending)
                pending = None

        return channels

    async def list_channels(
        self,
        favorites_only: bool = False,
        group: Optional[str] = None,
        with_epg: bool = False,
    ) -> List[Dict[str, Any]]:
        async with get_db_session() as db:
            stmt = select(IptvChannel).where(IptvChannel.is_active.is_(True))
            if favorites_only:
                stmt = stmt.where(IptvChannel.is_favorite.is_(True))
            if group:
                stmt = stmt.where(IptvChannel.group_name == group)
            stmt = stmt.order_by(IptvChannel.group_name.asc().nulls_last(), IptvChannel.name)
            result = await db.execute(stmt)
            channels = [self._channel_dict(c) for c in result.scalars().all()]

        if with_epg:
            epg_ids = [c["epg_id"] for c in channels if c.get("epg_id")]
            guide = await self.epg.guide_for_channels(epg_ids, hours=3)
            for c in channels:
                epg_id = c.get("epg_id")
                programs = guide.get(epg_id or "", [])
                c["now"] = next((p for p in programs if p.get("is_now")), None)
                c["next"] = next((p for p in programs if not p.get("is_now")), None)
                c["play_url"] = f"/api/v1/entertainment/stream/iptv/{c['id']}"
        else:
            for c in channels:
                c["play_url"] = f"/api/v1/entertainment/stream/iptv/{c['id']}"
        return channels

    async def get_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        async with get_db_session() as db:
            result = await db.execute(select(IptvChannel).where(IptvChannel.id == channel_id))
            channel = result.scalar_one_or_none()
            if not channel:
                return None
            data = self._channel_dict(channel)
            data["play_url"] = f"/api/v1/entertainment/stream/iptv/{channel.id}"
            if channel.epg_id:
                data.update(await self.epg.now_and_next(channel.epg_id))
            return data

    async def favorite_channel(self, channel_id: str, favorite: bool = True) -> Optional[Dict[str, Any]]:
        async with get_db_session() as db:
            result = await db.execute(select(IptvChannel).where(IptvChannel.id == channel_id))
            channel = result.scalar_one_or_none()
            if not channel:
                return None
            channel.is_favorite = favorite
            await db.commit()
            await db.refresh(channel)
            return self._channel_dict(channel)

    async def list_groups(self) -> List[str]:
        async with get_db_session() as db:
            result = await db.execute(
                select(IptvChannel.group_name)
                .where(IptvChannel.is_active.is_(True), IptvChannel.group_name.is_not(None))
                .distinct()
                .order_by(IptvChannel.group_name)
            )
            return [g for g in result.scalars().all() if g]

    async def list_stations(
        self,
        favorites_only: bool = False,
        genre: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        async with get_db_session() as db:
            stmt = select(RadioStation).where(RadioStation.is_active.is_(True))
            if favorites_only:
                stmt = stmt.where(RadioStation.is_favorite.is_(True))
            if genre:
                stmt = stmt.where(RadioStation.genre == genre)
            stmt = stmt.order_by(RadioStation.name)
            result = await db.execute(stmt)
            stations = [self._station_dict(s) for s in result.scalars().all()]
        for s in stations:
            s["play_url"] = f"/api/v1/entertainment/stream/radio/{s['id']}"
        return stations

    async def create_station(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with get_db_session() as db:
            station = RadioStation(
                name=data["name"],
                stream_url=data["stream_url"],
                logo_url=data.get("logo_url"),
                genre=data.get("genre"),
                country=data.get("country"),
                is_favorite=bool(data.get("is_favorite", False)),
            )
            db.add(station)
            await db.commit()
            await db.refresh(station)
            out = self._station_dict(station)
            out["play_url"] = f"/api/v1/entertainment/stream/radio/{station.id}"
            return out

    async def favorite_station(self, station_id: str, favorite: bool = True) -> Optional[Dict[str, Any]]:
        async with get_db_session() as db:
            result = await db.execute(select(RadioStation).where(RadioStation.id == station_id))
            station = result.scalar_one_or_none()
            if not station:
                return None
            station.is_favorite = favorite
            await db.commit()
            await db.refresh(station)
            return self._station_dict(station)

    async def get_stream_source(self, kind: str, item_id: str) -> Optional[Dict[str, str]]:
        async with get_db_session() as db:
            if kind == "radio":
                result = await db.execute(select(RadioStation).where(RadioStation.id == item_id))
                row = result.scalar_one_or_none()
            else:
                result = await db.execute(select(IptvChannel).where(IptvChannel.id == item_id))
                row = result.scalar_one_or_none()
            if not row:
                return None
            return {"name": row.name, "stream_url": row.stream_url}

    async def schedule_recording(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with get_db_session() as db:
            recording = Recording(
                title=data["title"],
                source_type=data.get("source_type", "iptv"),
                source_id=data["source_id"],
                duration_seconds=data.get("duration_seconds"),
                status="scheduled",
                scheduled_start=data["scheduled_start"],
                scheduled_end=data["scheduled_end"],
            )
            db.add(recording)
            await db.commit()
            await db.refresh(recording)
            return self._recording_dict(recording)

    async def list_recordings(self) -> List[Dict[str, Any]]:
        async with get_db_session() as db:
            result = await db.execute(
                select(Recording).order_by(Recording.scheduled_start.desc())
            )
            return [self._recording_dict(r) for r in result.scalars().all()]

    async def process_due_recordings(self) -> int:
        now = datetime.now(timezone.utc)
        async with get_db_session() as db:
            result = await db.execute(
                select(Recording).where(
                    Recording.status == "scheduled",
                    Recording.scheduled_start <= now,
                )
            )
            due = list(result.scalars().all())

        for rec in due:
            await self._run_recording(rec.id)
        return len(due)

    async def _run_recording(self, recording_id: str) -> None:
        async with get_db_session() as db:
            result = await db.execute(select(Recording).where(Recording.id == recording_id))
            rec = result.scalar_one_or_none()
            if not rec or rec.status != "scheduled":
                return

            stream_url = await self._resolve_stream_url(db, rec.source_type, rec.source_id)
            title = rec.title
            source_type = rec.source_type
            rec.status = "recording"
            rec.actual_start = datetime.now(timezone.utc)
            await db.commit()

            duration = rec.duration_seconds
            if duration is None and rec.scheduled_end and rec.scheduled_start:
                duration = max(1, int((rec.scheduled_end - rec.scheduled_start).total_seconds()))
            max_dur = int(settings.recording_max_duration_seconds or 14400)
            duration = min(duration or 3600, max_dur)

        out_dir = settings.media_root / "recordings"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in title).strip()
        out_path = out_dir / f"{safe_title}_{recording_id[:8]}.mkv"

        ffmpeg = shutil.which("ffmpeg")
        error = None
        if not stream_url:
            error = "No stream_url for source"
        elif not ffmpeg:
            error = "ffmpeg not available"
        else:
            cmd = [
                ffmpeg, "-y",
                "-i", stream_url,
                "-t", str(duration),
                "-c", "copy",
                str(out_path),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    error = (stderr or b"").decode("utf-8", errors="ignore")[-500:] or f"ffmpeg {proc.returncode}"
            except Exception as exc:
                error = str(exc)

        # Optionally copy into library for Jellyfin discovery
        final_path = out_path
        if out_path.exists() and settings.recording_organize_to_library:
            lib_dir = settings.library_root / "recordings"
            lib_dir.mkdir(parents=True, exist_ok=True)
            dest = lib_dir / out_path.name
            try:
                shutil.copy2(str(out_path), str(dest))
                final_path = dest
            except OSError as exc:
                logger.warning("Failed to copy recording to library", error=str(exc))

        async with get_db_session() as db:
            result = await db.execute(select(Recording).where(Recording.id == recording_id))
            rec = result.scalar_one_or_none()
            if not rec:
                return
            rec.actual_end = datetime.now(timezone.utc)
            if error and not out_path.exists():
                rec.status = "failed"
                rec.error_message = error
            else:
                rec.status = "completed"
                rec.file_path = str(final_path)
                if final_path.exists():
                    rec.file_size_bytes = final_path.stat().st_size
                rec.duration_seconds = duration
                if error:
                    rec.error_message = error
            await db.commit()
            logger.info("Recording finished", recording_id=recording_id, status=rec.status, source_type=source_type)

    async def _resolve_stream_url(self, db, source_type: str, source_id: str) -> Optional[str]:
        if source_type == "radio":
            result = await db.execute(select(RadioStation).where(RadioStation.id == source_id))
            station = result.scalar_one_or_none()
            return station.stream_url if station else None
        result = await db.execute(select(IptvChannel).where(IptvChannel.id == source_id))
        channel = result.scalar_one_or_none()
        return channel.stream_url if channel else None

    async def export_m3u(self) -> str:
        """Jellyfin-compatible M3U with proxied stream URLs."""
        base = settings.public_base_url.rstrip("/")
        channels = await self.list_channels()
        lines = ["#EXTM3U"]
        for ch in channels:
            epg = ch.get("epg_id") or ""
            logo = ch.get("logo_url") or ""
            group = ch.get("group_name") or "IPTV"
            attrs = f'tvg-id="{epg}" tvg-name="{ch["name"]}" tvg-logo="{logo}" group-title="{group}"'
            lines.append(f'#EXTINF:-1 {attrs},{ch["name"]}')
            lines.append(f'{base}/api/v1/entertainment/stream/iptv/{ch["id"]}')
        return "\n".join(lines) + "\n"

    async def export_xmltv(self) -> str:
        """XMLTV export for channels that have epg_id + stored programmes."""
        channels = await self.list_channels()
        epg_ids = sorted({c["epg_id"] for c in channels if c.get("epg_id")})
        guide = await self.epg.guide_for_channels(epg_ids, hours=48)

        parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv generator-info-name="media-platform">']
        seen = set()
        for ch in channels:
            epg_id = ch.get("epg_id")
            if not epg_id or epg_id in seen:
                continue
            seen.add(epg_id)
            parts.append(f'  <channel id="{escape(epg_id)}">')
            parts.append(f'    <display-name>{escape(ch["name"])}</display-name>')
            if ch.get("logo_url"):
                parts.append(f'    <icon src="{escape(ch["logo_url"])}" />')
            parts.append("  </channel>")

        def fmt(iso: str) -> str:
            # 2026-07-22T12:00:00+00:00 -> 20260722120000 +0000
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
            return dt.strftime("%Y%m%d%H%M%S +0000")

        for epg_id, programs in guide.items():
            for p in programs:
                parts.append(
                    f'  <programme start="{fmt(p["start_at"])}" stop="{fmt(p["end_at"])}" channel="{escape(epg_id)}">'
                )
                parts.append(f'    <title>{escape(p["title"])}</title>')
                if p.get("description"):
                    parts.append(f'    <desc>{escape(p["description"])}</desc>')
                if p.get("category"):
                    parts.append(f'    <category>{escape(p["category"])}</category>')
                parts.append("  </programme>")
        parts.append("</tv>")
        return "\n".join(parts) + "\n"

    @staticmethod
    def _channel_dict(c: IptvChannel) -> Dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "stream_url": c.stream_url,
            "logo_url": c.logo_url,
            "group_name": c.group_name,
            "epg_id": c.epg_id,
            "is_favorite": c.is_favorite,
            "is_active": c.is_active,
        }

    @staticmethod
    def _station_dict(s: RadioStation) -> Dict[str, Any]:
        return {
            "id": s.id,
            "name": s.name,
            "stream_url": s.stream_url,
            "logo_url": s.logo_url,
            "genre": s.genre,
            "country": s.country,
            "is_favorite": s.is_favorite,
            "is_active": s.is_active,
        }

    @staticmethod
    def _recording_dict(r: Recording) -> Dict[str, Any]:
        return {
            "id": r.id,
            "title": r.title,
            "source_type": r.source_type,
            "source_id": r.source_id,
            "file_path": r.file_path,
            "file_size_bytes": r.file_size_bytes,
            "duration_seconds": r.duration_seconds,
            "status": r.status,
            "error_message": r.error_message,
            "scheduled_start": r.scheduled_start.isoformat() if r.scheduled_start else None,
            "scheduled_end": r.scheduled_end.isoformat() if r.scheduled_end else None,
            "actual_start": r.actual_start.isoformat() if r.actual_start else None,
            "actual_end": r.actual_end.isoformat() if r.actual_end else None,
        }
