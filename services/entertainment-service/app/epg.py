"""
XMLTV EPG fetch and parse.
"""
from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.entertainment import EpgProgram
from shared.logging.logger import get_logger
from sqlalchemy import delete, select

logger = get_logger("epg")


def _parse_xmltv_time(value: str) -> Optional[datetime]:
    """Parse XMLTV timestamps like 20260722120000 +0000 or 20260722120000."""
    if not value:
        return None
    raw = value.strip()
    tz = timezone.utc
    if " " in raw:
        stamp, offset = raw.split(" ", 1)
        offset = offset.strip()
        if len(offset) >= 5 and offset[0] in "+-":
            sign = 1 if offset[0] == "+" else -1
            hours = int(offset[1:3])
            mins = int(offset[3:5])
            from datetime import timedelta

            tz = timezone(sign * timedelta(hours=hours, minutes=mins))
    else:
        stamp = raw
    stamp = stamp[:14]
    try:
        dt = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=tz).astimezone(timezone.utc)
    except ValueError:
        return None


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None or el.text is None:
        return None
    return " ".join(el.text.split())


class EpgManager:
    """Download XMLTV and persist programmes."""

    async def refresh(self, url: Optional[str] = None) -> Dict[str, Any]:
        epg_url = (url or settings.epg_url or "").strip()
        if not epg_url:
            raise ValueError("EPG_URL is not configured")

        content = await self._download(epg_url)
        programs = self._parse_xmltv(content)
        stored = await self._replace_programs(programs)
        logger.info("EPG refresh complete", source=epg_url, programs=stored)
        return {"source": epg_url, "programs": stored}

    async def _download(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
            if url.lower().endswith(".gz") or data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return data

    def _parse_xmltv(self, content: bytes) -> List[Dict[str, Any]]:
        root = ET.fromstring(content)
        programs: List[Dict[str, Any]] = []
        for prog in root.findall("programme"):
            channel = prog.get("channel")
            start = _parse_xmltv_time(prog.get("start", ""))
            stop = _parse_xmltv_time(prog.get("stop", ""))
            if not channel or not start or not stop:
                continue
            title = _text(prog.find("title")) or "Untitled"
            desc = _text(prog.find("desc"))
            category = _text(prog.find("category"))
            episode = _text(prog.find("episode-num"))
            programs.append(
                {
                    "channel_epg_id": channel,
                    "title": title[:500],
                    "description": desc,
                    "category": category[:100] if category else None,
                    "start_at": start,
                    "end_at": stop,
                    "episode_num": episode[:50] if episode else None,
                }
            )
        return programs

    async def _replace_programs(self, programs: List[Dict[str, Any]]) -> int:
        async with get_db_session() as db:
            await db.execute(delete(EpgProgram))
            # Chunk inserts
            batch: List[EpgProgram] = []
            for item in programs:
                batch.append(EpgProgram(**item))
                if len(batch) >= 500:
                    db.add_all(batch)
                    await db.flush()
                    batch = []
            if batch:
                db.add_all(batch)
            await db.commit()
        return len(programs)

    async def guide_for_channels(
        self,
        channel_epg_ids: List[str],
        *,
        around: Optional[datetime] = None,
        hours: int = 6,
    ) -> Dict[str, List[Dict[str, Any]]]:
        from datetime import timedelta

        now = around or datetime.now(timezone.utc)
        window_end = now + timedelta(hours=hours)
        result: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in channel_epg_ids}
        if not channel_epg_ids:
            return result

        async with get_db_session() as db:
            stmt = (
                select(EpgProgram)
                .where(
                    EpgProgram.channel_epg_id.in_(channel_epg_ids),
                    EpgProgram.end_at >= now,
                    EpgProgram.start_at <= window_end,
                )
                .order_by(EpgProgram.start_at)
            )
            rows = (await db.execute(stmt)).scalars().all()
            for row in rows:
                result.setdefault(row.channel_epg_id, []).append(
                    {
                        "id": row.id,
                        "channel_epg_id": row.channel_epg_id,
                        "title": row.title,
                        "description": row.description,
                        "category": row.category,
                        "start_at": row.start_at.isoformat(),
                        "end_at": row.end_at.isoformat(),
                        "episode_num": row.episode_num,
                        "is_now": row.start_at <= now < row.end_at,
                    }
                )
        return result

    async def now_and_next(self, channel_epg_id: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        async with get_db_session() as db:
            current = (
                await db.execute(
                    select(EpgProgram)
                    .where(
                        EpgProgram.channel_epg_id == channel_epg_id,
                        EpgProgram.start_at <= now,
                        EpgProgram.end_at > now,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            upcoming = (
                await db.execute(
                    select(EpgProgram)
                    .where(
                        EpgProgram.channel_epg_id == channel_epg_id,
                        EpgProgram.start_at > now,
                    )
                    .order_by(EpgProgram.start_at)
                    .limit(1)
                )
            ).scalar_one_or_none()

        def ser(p: Optional[EpgProgram]) -> Optional[Dict[str, Any]]:
            if not p:
                return None
            return {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "category": p.category,
                "start_at": p.start_at.isoformat(),
                "end_at": p.end_at.isoformat(),
            }

        return {"now": ser(current), "next": ser(upcoming)}
