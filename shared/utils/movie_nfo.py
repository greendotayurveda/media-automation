"""
Parse Jellyfin/Kodi movie.nfo (or movie.info) beside library videos.

Used by smart reorganize as a local metadata source before OMDb/TMDb.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.logging.logger import get_logger
from shared.utils.library_category import normalize_language_code, parse_genre_list

logger = get_logger("movie-nfo")

# Prefer these names in the movie folder (Jellyfin writes movie.nfo).
_NFO_BASENAMES = ("movie.nfo", "movie.info", "movie.xml")


def find_movie_nfo(folder: Path, video: Optional[Path] = None) -> Optional[Path]:
    """Locate movie.nfo / movie.info next to the video or named like the video stem."""
    if folder.is_dir():
        for name in _NFO_BASENAMES:
            candidate = folder / name
            if candidate.is_file():
                return candidate

    if video is not None:
        sibling = video.with_suffix(".nfo")
        if sibling.is_file():
            return sibling
        info_sibling = video.parent / f"{video.stem}.info"
        if info_sibling.is_file():
            return info_sibling

    return None


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None or el.text is None:
        return None
    value = el.text.strip()
    return value or None


def _all_texts(root: ET.Element, tag: str) -> List[str]:
    values: List[str] = []
    for el in root.findall(tag):
        text = _text(el)
        if text:
            values.append(text)
    return values


def _parse_year(root: ET.Element) -> Optional[int]:
    raw = _text(root.find("year"))
    if not raw:
        premiered = _text(root.find("premiered")) or _text(root.find("releasedate"))
        if premiered and len(premiered) >= 4 and premiered[:4].isdigit():
            raw = premiered[:4]
    if not raw:
        return None
    try:
        year = int(raw[:4])
    except ValueError:
        return None
    if 1880 <= year <= 2100:
        return year
    return None


def _parse_rating(root: ET.Element) -> Optional[float]:
    raw = _text(root.find("rating"))
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_ids(root: ET.Element) -> Dict[str, Any]:
    imdb = _text(root.find("imdbid")) or _text(root.find("imdb_id"))
    tmdb_raw = _text(root.find("tmdbid")) or _text(root.find("tmdb_id"))
    # Some NFOs put imdb in <id>
    generic_id = _text(root.find("id"))
    if not imdb and generic_id and generic_id.lower().startswith("tt"):
        imdb = generic_id

    tmdb_id: Optional[int] = None
    if tmdb_raw and tmdb_raw.isdigit():
        tmdb_id = int(tmdb_raw)

    return {"imdb_id": imdb, "tmdb_id": tmdb_id}


def _parse_audio_language(root: ET.Element) -> Optional[str]:
    """Use first streamdetails/audio/language as main language (e.g. hin → hi)."""
    for audio in root.findall("./fileinfo/streamdetails/audio"):
        lang = _text(audio.find("language"))
        if lang:
            return normalize_language_code(lang)
    # Rare: top-level <language>
    top = _text(root.find("language"))
    if top:
        return normalize_language_code(top)
    return None


def parse_movie_nfo(path: Path) -> Optional[Dict[str, Any]]:
    """
    Parse a Jellyfin/Kodi movie NFO into metadata dict compatible with reorganize.

    Returns None if the file is missing or unreadable.
    """
    try:
        if not path.is_file():
            return None
        tree = ET.parse(path)
        root = tree.getroot()
    except (ET.ParseError, OSError) as exc:
        logger.warning("Failed to parse movie NFO", path=str(path), error=str(exc))
        return None

    # Accept <movie> root or nested.
    if root.tag.lower() != "movie":
        nested = root.find("movie")
        if nested is not None:
            root = nested

    genres = parse_genre_list(_all_texts(root, "genre"))
    ids = _parse_ids(root)
    language = _parse_audio_language(root)
    rating = _parse_rating(root)

    title = _text(root.find("title"))
    original_title = _text(root.find("originaltitle"))
    overview = _text(root.find("plot"))
    year = _parse_year(root)

    # Local artwork paths from <art> (optional; may be Jellyfin container paths)
    poster_url = None
    backdrop_url = None
    art = root.find("art")
    if art is not None:
        poster_url = _text(art.find("poster"))
        backdrop_url = _text(art.find("fanart")) or _text(art.find("backdrop"))

    return {
        "provider": "nfo",
        "nfo_path": str(path),
        "title": title,
        "original_title": original_title,
        "year": year,
        "overview": overview,
        "original_language": language,
        "genres": genres,
        "imdb_id": ids.get("imdb_id"),
        "tmdb_id": ids.get("tmdb_id"),
        "rating_imdb": rating,
        "poster_url": poster_url,
        "backdrop_url": backdrop_url,
    }


def load_movie_nfo_metadata(folder: Path, video: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Find and parse NFO for a movie folder/video."""
    nfo = find_movie_nfo(folder, video)
    if not nfo:
        return None
    return parse_movie_nfo(nfo)
