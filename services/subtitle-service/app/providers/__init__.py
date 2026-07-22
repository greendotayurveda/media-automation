"""Subtitle provider package."""
from app.providers.opensubtitles import OpenSubtitlesProvider
from app.providers.subdl import SubDLProvider

__all__ = ["OpenSubtitlesProvider", "SubDLProvider"]
