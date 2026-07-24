"""
Map movie metadata (language + genre) to library folder segments.

Example paths:
  library/malayalam/action/Jana Nayagan (2026)/
  library/hollywood/horror/Alien (1979)/
  library/bollywood/comedy/Title (Year)/
  library/other/other/Unknown/
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from shared.config.settings import settings

# OMDb returns full language names; TMDb returns ISO 639-1 codes.
_LANGUAGE_NAME_TO_CODE: Dict[str, str] = {
    "malayalam": "ml",
    "tamil": "ta",
    "hindi": "hi",
    "telugu": "te",
    "kannada": "kn",
    "english": "en",
    "korean": "ko",
    "japanese": "ja",
    "chinese": "zh",
    "mandarin": "zh",
    "cantonese": "zh",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "arabic": "ar",
    "bengali": "bn",
    "marathi": "mr",
    "punjabi": "pa",
    "urdu": "ur",
}

# Normalize provider genre labels → folder slug
_GENRE_ALIASES: Dict[str, str] = {
    "science fiction": "scifi",
    "sci-fi": "scifi",
    "sci fi": "scifi",
    "science-fiction": "scifi",
    "tv movie": "tv-movie",
    "film-noir": "noir",
    "film noir": "noir",
    "musical": "music",
    "war": "war",
    "western": "western",
    "biography": "biography",
    "sport": "sport",
    "history": "history",
    "news": "documentary",
}


def parse_kv_map(raw: str) -> Dict[str, str]:
    """Parse `a:b,c:d` into {a: b}."""
    mapping: Dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, folder = part.split(":", 1)
        key = key.strip().lower()
        folder = _sanitize_segment(folder.strip())
        if key and folder:
            mapping[key] = folder
    return mapping


def parse_language_map(raw: str) -> Dict[str, str]:
    return parse_kv_map(raw)


def normalize_language_code(value: Optional[str]) -> Optional[str]:
    """Normalize TMDb code or OMDb language name to a 2–3 letter code."""
    if not value:
        return None
    first = str(value).split(",")[0].strip()
    if not first or first.upper() == "N/A":
        return None
    lower = first.lower()
    if lower in _LANGUAGE_NAME_TO_CODE:
        return _LANGUAGE_NAME_TO_CODE[lower]
    token = re.split(r"[-_]", lower)[0]
    if re.fullmatch(r"[a-z]{2,3}", token):
        return token
    return _LANGUAGE_NAME_TO_CODE.get(lower)


def normalize_genre_name(value: Optional[str]) -> Optional[str]:
    """Normalize a single genre label to a folder slug (e.g. Action → action)."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw or raw.upper() == "N/A":
        return None
    lower = raw.lower()
    aliases = {**_GENRE_ALIASES, **parse_kv_map(settings.library_genre_aliases)}
    if lower in aliases:
        return _sanitize_segment(aliases[lower])
    return _sanitize_segment(lower.replace(" ", "-"))


def parse_genre_list(value: Any) -> List[str]:
    """Accept list[str], list[dict{name}], or comma-separated string."""
    if value is None:
        return []
    names: List[str] = []
    if isinstance(value, str):
        names = [p.strip() for p in value.split(",") if p.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if isinstance(item, str):
                names.append(item.strip())
            elif isinstance(item, Mapping):
                name = item.get("name") or item.get("genre")
                if name:
                    names.append(str(name).strip())
    return [n for n in names if n and n.upper() != "N/A"]


def pick_primary_genre(genres: Iterable[str]) -> Optional[str]:
    """
    Choose one genre folder using LIBRARY_GENRE_PRIORITY order.
    First matching priority wins; else first normalized genre; else None.
    """
    normalized = [normalize_genre_name(g) for g in genres]
    normalized = [g for g in normalized if g]
    if not normalized:
        return None

    priority = [
        _sanitize_segment(p.strip().lower().replace(" ", "-"))
        for p in (settings.library_genre_priority or "").split(",")
        if p.strip()
    ]
    for pref in priority:
        if pref in normalized:
            return pref
    return normalized[0]


def _sanitize_segment(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "")
    cleaned = name.strip().strip(".").replace(" ", "-").lower()
    return cleaned or "other"


def resolve_library_category(
    *,
    original_language: Optional[str] = None,
    origin_country: Optional[str] = None,
    genres: Optional[list] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> str:
    """Language (or legacy movies) folder only — kept for callers that need a single segment."""
    lang_folder, _genre = resolve_library_segments(
        original_language=original_language,
        origin_country=origin_country,
        genres=genres,
        payload=payload,
    )
    return lang_folder


def resolve_library_segments(
    *,
    original_language: Optional[str] = None,
    origin_country: Optional[str] = None,
    genres: Optional[Union[list, str]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> tuple[str, Optional[str]]:
    """
    Return (language_folder, genre_folder_or_None).

    When LIBRARY_CATEGORIZE_BY_LANGUAGE=false → ("movies", optional genre if enabled).
    When LIBRARY_CATEGORIZE_BY_GENRE=true → genre folder under language.
    """
    data = dict(payload or {})
    _ = origin_country or data.get("origin_country")

    if not settings.library_categorize_by_language:
        lang_folder = "movies"
    else:
        lang = original_language or data.get("original_language") or data.get("language")
        code = normalize_language_code(str(lang) if lang else None)
        mapping = parse_language_map(settings.library_language_map)
        if code and code in mapping:
            lang_folder = mapping[code]
        else:
            lang_folder = _sanitize_segment(settings.library_default_category or "other")

    genre_folder: Optional[str] = None
    if settings.library_categorize_by_genre:
        raw_genres = genres if genres is not None else data.get("genres") or data.get("genre")
        if not raw_genres and data.get("primary_genre"):
            raw_genres = [data.get("primary_genre")]
        primary = pick_primary_genre(parse_genre_list(raw_genres))
        genre_folder = primary or _sanitize_segment(settings.library_default_genre or "other")

    return lang_folder, genre_folder


def resolve_library_relative_path(
    *,
    original_language: Optional[str] = None,
    genres: Optional[Union[list, str]] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Relative path under library_root, e.g. Path('malayalam/action')."""
    lang_folder, genre_folder = resolve_library_segments(
        original_language=original_language,
        genres=genres,
        payload=payload,
    )
    if genre_folder:
        return Path(lang_folder) / genre_folder
    return Path(lang_folder)
