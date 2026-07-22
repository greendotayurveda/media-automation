"""
qBittorrent WebUI API client (httpx, cookie auth).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import httpx

from shared.config.settings import settings
from shared.exceptions.base import DownloadError
from shared.logging.logger import get_logger

logger = get_logger("qbittorrent-client")

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts"}
DONE_STATES = {
    "uploading",
    "stalledUP",
    "pausedUP",
    "queuedUP",
    "forcedUP",
    "checkingUP",
}
FAIL_STATES = {"error", "missingFiles"}


def is_torrent_link(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    lower = value.lower()
    if lower.startswith("magnet:?"):
        return True
    if lower.startswith("qbittorrent://"):
        return True
    if lower.endswith(".torrent"):
        return True
    if "magnet:?xt=urn:btih:" in lower:
        return True
    return False


def extract_torrent_links(text: str) -> List[str]:
    """Pull magnet / torrent / qbittorrent links from free-form message text."""
    if not text:
        return []
    found: List[str] = []
    # Magnets (may contain &amp; in HTML; Telegram usually sends raw)
    for match in re.finditer(r"magnet:\?[^\s<>\"']+", text, flags=re.IGNORECASE):
        link = match.group(0).rstrip(").,];")
        if link not in found:
            found.append(link)
    # qbittorrent://download/... or similar
    for match in re.finditer(r"qbittorrent:[^\s<>\"']+", text, flags=re.IGNORECASE):
        link = match.group(0).rstrip(").,];")
        if link not in found:
            found.append(link)
    # HTTP(S) .torrent URLs
    for match in re.finditer(r"https?://[^\s<>\"']+\.torrent(?:\?[^\s<>\"']*)?", text, flags=re.IGNORECASE):
        link = match.group(0).rstrip(").,];")
        if link not in found:
            found.append(link)
    return found


def magnet_info_hash(magnet: str) -> Optional[str]:
    match = re.search(r"xt=urn:btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})", magnet, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1)
    # Base32 → leave as-is; qBittorrent accepts both; normalize hex to lower
    if len(value) == 40:
        return value.lower()
    return value.upper()


def normalize_qbittorrent_url(link: str) -> str:
    """Convert qbittorrent:// links to magnet when possible."""
    if not link.lower().startswith("qbittorrent:"):
        return link
    # Common form: qbittorrent://download/magnet:?xt=...
    decoded = unquote(link)
    magnet_idx = decoded.lower().find("magnet:?")
    if magnet_idx >= 0:
        return decoded[magnet_idx:]
    # Some clients embed btih only
    hash_match = re.search(r"([a-fA-F0-9]{40})", decoded)
    if hash_match:
        return f"magnet:?xt=urn:btih:{hash_match.group(1).lower()}"
    return link


class QBittorrentClient:
    """Minimal async WebUI client for add + poll + file discovery."""

    def __init__(self) -> None:
        self.base_url = settings.qbittorrent_url.rstrip("/")
        self.username = settings.qbittorrent_username
        self.password = settings.qbittorrent_password
        self.category = settings.qbittorrent_category
        self.save_path = settings.qbittorrent_save_path
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.password)

    async def __aenter__(self) -> "QBittorrentClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            follow_redirects=True,
        )
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def login(self) -> None:
        assert self._client is not None
        resp = await self._client.post(
            "/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )
        body = resp.text.strip().lower()
        if resp.status_code not in (200, 204) or body == "fails.":
            raise DownloadError(
                "qBittorrent login failed",
                status=resp.status_code,
                body=resp.text[:200],
            )
        logger.info("Authenticated with qBittorrent WebUI")

    async def add_magnet_or_url(
        self,
        url: str,
        *,
        tag: Optional[str] = None,
    ) -> str:
        """Add magnet or .torrent HTTP URL. Returns best-effort infohash."""
        assert self._client is not None
        url = normalize_qbittorrent_url(url)
        data: Dict[str, Any] = {
            "urls": url,
            "savepath": self.save_path,
            "category": self.category,
            "paused": "false",
        }
        if tag:
            data["tags"] = tag

        resp = await self._client.post("/api/v2/torrents/add", data=data)
        if resp.status_code != 200 or "fail" in resp.text.lower():
            raise DownloadError(
                "qBittorrent failed to add torrent",
                status=resp.status_code,
                body=resp.text[:300],
            )

        info_hash = magnet_info_hash(url) if url.lower().startswith("magnet:") else None
        if not info_hash:
            # Resolve by newest torrent in category
            info_hash = await self._find_recent_hash(prefer_name=Path(urlparse(url).path).name)
        if not info_hash:
            raise DownloadError("Torrent added but infohash could not be resolved")
        logger.info("Torrent added to qBittorrent", hash=info_hash)
        return info_hash

    async def add_torrent_file(
        self,
        torrent_path: Path,
        *,
        tag: Optional[str] = None,
    ) -> str:
        assert self._client is not None
        files = {"torrents": (torrent_path.name, torrent_path.read_bytes(), "application/x-bittorrent")}
        data: Dict[str, Any] = {
            "savepath": self.save_path,
            "category": self.category,
            "paused": "false",
        }
        if tag:
            data["tags"] = tag
        resp = await self._client.post("/api/v2/torrents/add", data=data, files=files)
        if resp.status_code != 200 or "fail" in resp.text.lower():
            raise DownloadError(
                "qBittorrent failed to add torrent file",
                status=resp.status_code,
                body=resp.text[:300],
            )
        info_hash = await self._find_recent_hash(prefer_name=torrent_path.stem)
        if not info_hash:
            raise DownloadError("Torrent file added but infohash could not be resolved")
        return info_hash

    async def get_torrent(self, info_hash: str) -> Optional[Dict[str, Any]]:
        assert self._client is not None
        resp = await self._client.get("/api/v2/torrents/info", params={"hashes": info_hash})
        resp.raise_for_status()
        items = resp.json()
        return items[0] if items else None

    async def list_files(self, info_hash: str) -> List[Dict[str, Any]]:
        assert self._client is not None
        resp = await self._client.get("/api/v2/torrents/files", params={"hash": info_hash})
        resp.raise_for_status()
        return resp.json()

    async def pick_primary_video(self, info_hash: str, content_path: str) -> Optional[Path]:
        """Choose the largest video file from a completed torrent."""
        files = await self.list_files(info_hash)
        video_files = []
        for item in files:
            name = item.get("name") or ""
            if Path(name).suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(item)
        if not video_files:
            # Fall back to largest file overall
            video_files = list(files)
        if not video_files:
            return None
        best = max(video_files, key=lambda f: int(f.get("size") or 0))
        rel = best.get("name") or ""
        root = Path(content_path)
        # content_path may be the file itself (single-file torrent) or a folder
        candidate = root / rel if root.is_dir() else root
        if candidate.exists() and candidate.is_file():
            return candidate
        # Try join under save_path
        alt = Path(self.save_path) / rel
        if alt.exists():
            return alt
        if root.exists() and root.is_file():
            return root
        return None

    async def _find_recent_hash(self, prefer_name: str = "") -> Optional[str]:
        assert self._client is not None
        params: Dict[str, str] = {"sort": "added_on", "reverse": "true"}
        if self.category:
            params["category"] = self.category
        resp = await self._client.get("/api/v2/torrents/info", params=params)
        resp.raise_for_status()
        torrents = resp.json()
        if not torrents:
            return None
        if prefer_name:
            for t in torrents[:10]:
                name = (t.get("name") or "").lower()
                if prefer_name.lower() in name or Path(prefer_name).stem.lower() in name:
                    return t.get("hash")
        return torrents[0].get("hash")
