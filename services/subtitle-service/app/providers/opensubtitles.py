"""
OpenSubtitles.com REST API provider (api.opensubtitles.com v1).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from shared.config.settings import settings
from shared.exceptions.base import SubtitleError, SubtitleNotFoundError
from shared.logging.logger import get_logger
from shared.utils.opensubtitles_hash import opensubtitles_movie_hash
from app.providers.base import SubtitleCandidate, SubtitleProvider

logger = get_logger("opensubtitles-provider")

API_BASE = "https://api.opensubtitles.com/api/v1"


class OpenSubtitlesProvider(SubtitleProvider):
    name = "opensubtitles"

    def __init__(self) -> None:
        self.api_key = settings.opensubtitles_api_key
        self.username = settings.opensubtitles_username
        self.password = settings.opensubtitles_password
        self.user_agent = settings.opensubtitles_user_agent
        self._token: Optional[str] = None

    def is_configured(self) -> bool:
        if not self.api_key:
            return False
        # Ignore documented sample/placeholder values
        blocked = {
            "placeholder",
            "changeme",
            "abc123def456ghi789jkl012mno345pq",
        }
        return self.api_key not in blocked

    def _headers(self, with_auth: bool = False) -> Dict[str, str]:
        headers = {
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if with_auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _ensure_token(self, client: httpx.AsyncClient) -> None:
        if self._token or not (self.username and self.password):
            return
        response = await client.post(
            f"{API_BASE}/login",
            headers=self._headers(),
            json={"username": self.username, "password": self.password},
            timeout=20.0,
        )
        if response.status_code >= 400:
            logger.warning(
                "OpenSubtitles login failed",
                status=response.status_code,
                body=response.text[:300],
            )
            return
        data = response.json()
        self._token = data.get("token")

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
            "languages": language,
            "type": "movie",
            "order_by": "download_count",
            "order_direction": "desc",
        }
        if tmdb_id:
            params["tmdb_id"] = tmdb_id
        if imdb_id:
            params["imdb_id"] = imdb_id.replace("tt", "")
        if title:
            params["query"] = title
        if year:
            params["year"] = year
        if file_path:
            try:
                params["moviehash"] = opensubtitles_movie_hash(file_path)
            except Exception as exc:
                logger.warning("OpenSubtitles hash failed", error=str(exc))

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE}/subtitles",
                headers=self._headers(),
                params=params,
                timeout=30.0,
            )
            if response.status_code >= 400:
                logger.warning(
                    "OpenSubtitles search failed",
                    status=response.status_code,
                    body=response.text[:300],
                )
                return []

            payload = response.json()
            items = payload.get("data") or []
            candidates: List[SubtitleCandidate] = []

            for item in items:
                attrs = item.get("attributes") or {}
                files = attrs.get("files") or []
                if not files:
                    continue
                file_info = files[0]
                file_id = file_info.get("file_id")
                if file_id is None:
                    continue

                # Prefer moviehash matches
                score = float(attrs.get("download_count") or 0)
                if attrs.get("moviehash_match"):
                    score += 1_000_000

                candidates.append(
                    SubtitleCandidate(
                        provider=self.name,
                        provider_id=str(file_id),
                        language=language,
                        release_name=attrs.get("release") or file_info.get("file_name") or "",
                        score=score,
                        hearing_impaired=bool(attrs.get("hearing_impaired")),
                        download_ref=file_id,
                    )
                )

            candidates.sort(key=lambda c: c.score, reverse=True)
            return candidates

    async def download(self, candidate: SubtitleCandidate, dest_path: Path) -> Path:
        if not self.is_configured():
            raise SubtitleError("OpenSubtitles API key is not configured")

        async with httpx.AsyncClient() as client:
            await self._ensure_token(client)
            response = await client.post(
                f"{API_BASE}/download",
                headers=self._headers(with_auth=True),
                json={"file_id": candidate.download_ref},
                timeout=30.0,
            )
            if response.status_code >= 400:
                raise SubtitleError(
                    f"OpenSubtitles download request failed ({response.status_code})",
                    body=response.text[:300],
                )

            data = response.json()
            link = data.get("link")
            if not link:
                raise SubtitleNotFoundError("OpenSubtitles returned no download link")

            file_response = await client.get(link, timeout=60.0)
            if file_response.status_code >= 400:
                raise SubtitleError(
                    f"OpenSubtitles file download failed ({file_response.status_code})"
                )

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(file_response.content)
            return dest_path
