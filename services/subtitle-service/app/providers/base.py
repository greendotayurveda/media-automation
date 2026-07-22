"""
Subtitle provider abstractions.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class SubtitleCandidate:
    provider: str
    provider_id: str
    language: str
    release_name: str = ""
    score: float = 0.0
    hearing_impaired: bool = False
    # Provider-specific download handle (file_id, url path, etc.)
    download_ref: Any = None


class SubtitleProvider(ABC):
    """Interface for external subtitle providers."""

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        ...

    @abstractmethod
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
    ) -> list[SubtitleCandidate]:
        ...

    @abstractmethod
    async def download(self, candidate: SubtitleCandidate, dest_path: Path) -> Path:
        ...
