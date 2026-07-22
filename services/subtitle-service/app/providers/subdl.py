"""
SubDL API provider (api.subdl.com v1).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from shared.config.settings import settings
from shared.exceptions.base import SubtitleError, SubtitleNotFoundError
from shared.logging.logger import get_logger
from app.providers.base import SubtitleCandidate, SubtitleProvider

logger = get_logger("subdl-provider")

API_BASE = "https://api.subdl.com/api/v1"
DL_BASE = "https://dl.subdl.com"


class SubDLProvider(SubtitleProvider):
    name = "subdl"

    def __init__(self) -> None:
        self.api_key = settings.subdl_api_key

    def is_configured(self) -> bool:
        return bool(self.api_key) and self.api_key not in ("placeholder", "changeme", "subdl_abc123def456ghi789")

    async def search(
        self,
        language: str,
        *,
        title: Optional[str] = None,
        year: Optional[int] = None,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
        tmdb_id: Optional[int] = None,
        imdb_id: Optional[str] = None,
    ) -> List[SubtitleCandidate]:
        if not self.is_configured():
            return []

        params: Dict[str, Any] = {
            "api_key": self.api_key,
            "type": "movie",
            "languages": language.upper(),
            "subs_per_page": 20,
            "client": "custom_integration",
        }
        if tmdb_id:
            params["tmdb_id"] = tmdb_id
        if imdb_id:
            params["imdb_id"] = imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}"
        if title:
            params["film_name"] = title
        if year:
            params["year"] = year
        if file_name:
            params["file_name"] = file_name

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE}/subtitles",
                params=params,
                timeout=30.0,
            )
            if response.status_code >= 400:
                logger.warning(
                    "SubDL search failed",
                    status=response.status_code,
                    body=response.text[:300],
                )
                return []

            payload = response.json()
            if not payload.get("status"):
                logger.warning("SubDL search returned error", error=payload.get("error"))
                return []

            candidates: List[SubtitleCandidate] = []
            for item in payload.get("subtitles") or []:
                url = item.get("url")
                if not url:
                    continue
                release = item.get("release_name") or item.get("name") or ""
                score = 10.0
                if file_name and file_name.lower() in release.lower():
                    score += 100.0

                candidates.append(
                    SubtitleCandidate(
                        provider=self.name,
                        provider_id=url,
                        language=language,
                        release_name=release,
                        score=score,
                        hearing_impaired=bool(item.get("hi")),
                        download_ref=url,
                    )
                )

            candidates.sort(key=lambda c: c.score, reverse=True)
            return candidates

    async def download(self, candidate: SubtitleCandidate, dest_path: Path) -> Path:
        if not self.is_configured():
            raise SubtitleError("SubDL API key is not configured")

        url_path = str(candidate.download_ref)
        if url_path.startswith("http"):
            download_url = url_path
        else:
            # API returns paths like /subtitle/123-456.zip
            cleaned = url_path.lstrip("/")
            if cleaned.startswith("subtitle/"):
                download_url = f"{DL_BASE}/{cleaned}"
            else:
                download_url = f"{DL_BASE}/subtitle/{cleaned}"

        params = {"api_key": self.api_key}
        headers = {"x-api-key": self.api_key}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                download_url,
                params=params,
                headers=headers,
                timeout=60.0,
                follow_redirects=True,
            )
            if response.status_code >= 400:
                raise SubtitleError(
                    f"SubDL download failed ({response.status_code})",
                    body=response.text[:300],
                )

            content = response.content
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if zipfile.is_zipfile(io.BytesIO(content)):
                srt_bytes = self._extract_srt_from_zip(content)
                if not srt_bytes:
                    raise SubtitleNotFoundError("SubDL zip contained no subtitle file")
                dest_path.write_bytes(srt_bytes)
            else:
                dest_path.write_bytes(content)

            return dest_path

    @staticmethod
    def _extract_srt_from_zip(content: bytes) -> Optional[bytes]:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [
                name
                for name in archive.namelist()
                if not name.endswith("/")
                and name.lower().endswith((".srt", ".vtt", ".ass", ".ssa"))
            ]
            if not names:
                # Fall back to first non-directory entry
                names = [name for name in archive.namelist() if not name.endswith("/")]
            if not names:
                return None
            # Prefer .srt
            names.sort(key=lambda n: (0 if n.lower().endswith(".srt") else 1, n))
            return archive.read(names[0])
