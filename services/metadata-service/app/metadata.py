"""
Metadata providers (TMDb / OMDb) and title/year filename parser.
Identifies media metadata and saves records into PostgreSQL.

OMDb is the practical primary source in regions where TMDb is ISP-blocked (e.g. India).
Order is controlled by METADATA_PROVIDERS (default: omdb,tmdb).
"""
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.logging.logger import get_logger

logger = get_logger("metadata-service")


class MetadataFetcher:
    """
    Parses media filenames and queries configured metadata providers.
    """

    def __init__(self) -> None:
        self.tmdb_api_key = settings.tmdb_api_key
        self.tmdb_base_url = settings.tmdb_base_url.rstrip("/")
        self.tmdb_image_base_url = settings.tmdb_image_base_url.rstrip("/")
        self.tmdb_http_proxy = settings.tmdb_http_proxy.strip() or None
        self.omdb_api_key = settings.omdb_api_key
        self.omdb_base_url = settings.omdb_base_url
        self.providers = settings.metadata_provider_list or ["tmdb", "omdb"]

    # Common pirate-site / mirror tokens seen in Indian release filenames.
    _SITE_TOKEN_RE = re.compile(
        r"""
        \b(
            www|
            \d*movierulz\d*|
            movierulz|
            tamilrockers?|
            tamilmv|
            moviesverse|
            moviezworld|
            masstamilan|
            isaimini|
            kinkimovies?|
            mhdtv|
            extramovies|
            skymovies|
            9xmovies|
            katmoviehd|
            hdmovies?hub|
            bollwood|
            bolly4u|
            software
        )\b
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    _QUALITY_RE = re.compile(
        r"""
        \b(
            2160p|1080p|720p|480p|360p|
            uhd|fhd|hdrip|brrip|bdrip|dvdrip|webrip|web-?dl|bluray|blu-?ray|
            x264|x265|h264|h265|hevc|avc|aac|dts|truehd|atmos|hdr10?\+?|dv|
            proper|repack|extended|unrated|etree|sample
        )\b
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    _YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

    def parse_filename(self, filename: str) -> Tuple[str, Optional[int]]:
        """
        Extract clean title + year from release/site-prefixed filenames.

        Handles patterns like:
          www 5MovieRulz software - Jana Nayagan ( (2026).mkv
          www.TamilRockers.-.Title.2024.1080p.mkv
          Title (2023).mkv
        """
        clean_name = Path(filename).stem
        clean_name = clean_name.replace(".", " ").replace("_", " ")
        clean_name = re.sub(r"\s+", " ", clean_name).strip()

        year_match = self._YEAR_RE.search(clean_name)
        year = int(year_match.group(1)) if year_match else None
        if year_match:
            # Prefer title text before the year (usual release layout).
            before = clean_name[: year_match.start()].strip()
            after = clean_name[year_match.end() :].strip()
            if before:
                clean_name = before
            elif after:
                clean_name = after

        clean_name = self._strip_site_prefix(clean_name)
        clean_name = self._QUALITY_RE.sub(" ", clean_name)
        clean_name = self._SITE_TOKEN_RE.sub(" ", clean_name)

        # Drop empty / broken brackets left by site naming: "( (", "[ ]", etc.
        clean_name = re.sub(r"[\(\[\{]+\s*[\)\]\}]*", " ", clean_name)
        clean_name = re.sub(r"[\)\]\}]+", " ", clean_name)
        clean_name = re.sub(r"^[\s\-\|:]+|[\s\-\|:]+$", "", clean_name)
        clean_name = re.sub(r"\s+", " ", clean_name).strip(" -_|:")

        if not clean_name:
            clean_name = Path(filename).stem.replace(".", " ").replace("_", " ").strip() or "Unknown"

        return clean_name, year

    def _strip_site_prefix(self, name: str) -> str:
        """
        If the name looks like `site junk - Real Title`, keep the real title.
        Also strip a leading www/site run without requiring a dash.
        """
        if " - " in name:
            left, right = name.split(" - ", 1)
            right_clean = right.strip()
            left_has_site = bool(self._SITE_TOKEN_RE.search(left)) or bool(
                re.search(r"rulz|rockers|moviesverse|tamilmv", left, re.I)
            )
            if right_clean and left_has_site:
                return right_clean

        stripped = re.sub(
            r"^(?:www\s+)?(?:\d+\s*)?(?:movierulz|tamilrockers?|tamilmv|moviesverse)\s*"
            r"(?:software\s*)?",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip(" -")
        return stripped or name
    async def identify_and_store_movie(self, file_path: str, payload_specs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve metadata via configured providers and upsert Movie by tmdb_id/imdb_id.
        """
        file_name = Path(file_path).name
        clean_title, year = self.parse_filename(file_name)

        resolved = await self._resolve_movie_metadata(clean_title, year)
        imdb_id = resolved.get("imdb_id")
        tmdb_id = resolved.get("tmdb_id")
        resolved_title = resolved.get("title") or clean_title
        resolved_year = year or resolved.get("year")
        poster_url = resolved.get("poster_url")
        backdrop_url = resolved.get("backdrop_url")
        overview = resolved.get("overview")
        original_title = resolved.get("original_title")
        rating_tmdb = resolved.get("rating_tmdb")
        rating_imdb = resolved.get("rating_imdb")
        provider = resolved.get("provider") or "filename"

        async with get_db_session() as db:
            movie = await self._find_existing_movie(db, tmdb_id=tmdb_id, imdb_id=imdb_id)
            existing_library_path = None
            is_update = movie is not None

            if movie:
                if movie.file_path and self._is_library_path(movie.file_path):
                    existing_library_path = movie.file_path

                movie.title = resolved_title
                movie.original_title = original_title or movie.original_title
                movie.year = resolved_year or movie.year
                movie.tmdb_id = tmdb_id or movie.tmdb_id
                movie.imdb_id = imdb_id or movie.imdb_id
                movie.overview = overview or movie.overview
                movie.rating_tmdb = rating_tmdb if rating_tmdb is not None else movie.rating_tmdb
                movie.rating_imdb = rating_imdb if rating_imdb is not None else movie.rating_imdb
                if poster_url:
                    movie.poster_url = poster_url
                if backdrop_url:
                    movie.backdrop_url = backdrop_url
            else:
                movie = Movie(
                    title=resolved_title,
                    original_title=original_title,
                    year=resolved_year,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    overview=overview,
                    rating_tmdb=rating_tmdb,
                    rating_imdb=rating_imdb,
                    poster_url=poster_url,
                    backdrop_url=backdrop_url,
                    file_path=file_path,
                    file_size_bytes=payload_specs.get("file_size_bytes"),
                )
                db.add(movie)

            await db.commit()
            await db.refresh(movie)

            logger.info(
                "Upserted movie metadata",
                movie_id=movie.id,
                title=movie.title,
                provider=provider,
                updated=is_update,
                existing_library_path=existing_library_path,
            )

            return {
                "movie_id": movie.id,
                "title": movie.title,
                "year": movie.year,
                "tmdb_id": movie.tmdb_id,
                "imdb_id": movie.imdb_id,
                "poster_url": movie.poster_url,
                "backdrop_url": movie.backdrop_url,
                "file_path": file_path,
                "existing_library_path": existing_library_path,
                "is_existing_movie": is_update,
                "metadata_provider": provider,
            }

    async def store_fallback_movie(self, file_path: str, payload_specs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Persist a minimal Movie from the filename so downstream steps have movie_id.
        """
        file_name = Path(file_path).name
        clean_title, year = self.parse_filename(file_name)
        title = clean_title or Path(file_name).stem or "Unknown"

        async with get_db_session() as db:
            movie = Movie(
                title=title,
                year=year,
                file_path=file_path,
                file_size_bytes=payload_specs.get("file_size_bytes") or payload_specs.get("file_size"),
            )
            db.add(movie)
            await db.commit()
            await db.refresh(movie)

            logger.warning(
                "Stored fallback movie metadata (no provider enrichment)",
                movie_id=movie.id,
                title=movie.title,
                year=movie.year,
            )

            return {
                "movie_id": movie.id,
                "title": movie.title,
                "year": movie.year,
                "tmdb_id": None,
                "imdb_id": None,
                "poster_url": None,
                "backdrop_url": None,
                "file_path": file_path,
                "existing_library_path": None,
                "is_existing_movie": False,
                "metadata_fallback": True,
                "metadata_provider": "filename",
            }

    async def _resolve_movie_metadata(self, title: str, year: Optional[int]) -> Dict[str, Any]:
        """Try providers in METADATA_PROVIDERS order; return first enriched hit."""
        for name in self.providers:
            if name == "tmdb":
                hit = await self._query_tmdb_movie(title, year)
            elif name == "omdb":
                hit = await self._query_omdb_movie(title, year)
            else:
                logger.warning("Unknown metadata provider skipped", provider=name)
                continue

            if hit:
                return hit

        logger.warning("All metadata providers missed; using parsed filename", title=title, year=year)
        return {
            "title": title,
            "year": year,
            "provider": "filename",
        }

    @staticmethod
    def _is_library_path(path: str) -> bool:
        try:
            resolved = Path(path).resolve()
            library = settings.library_root.resolve()
            return str(resolved).startswith(str(library))
        except (OSError, ValueError, AttributeError):
            return str(settings.library_root) in str(path)

    async def _find_existing_movie(
        self,
        db,
        *,
        tmdb_id: Optional[int],
        imdb_id: Optional[str],
    ) -> Optional[Movie]:
        if tmdb_id:
            result = await db.execute(select(Movie).where(Movie.tmdb_id == tmdb_id).limit(1))
            movie = result.scalar_one_or_none()
            if movie:
                return movie
        if imdb_id:
            result = await db.execute(select(Movie).where(Movie.imdb_id == imdb_id).limit(1))
            return result.scalar_one_or_none()
        return None

    def _tmdb_client_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"timeout": 15.0}
        if self.tmdb_http_proxy:
            kwargs["proxy"] = self.tmdb_http_proxy
        return kwargs

    async def _query_tmdb_movie(self, title: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
        """TMDb search + details. Returns None on block/error/miss so OMDb can run next."""
        if not self.tmdb_api_key:
            logger.info("TMDb skipped (TMDB_API_KEY empty)")
            return None

        url = f"{self.tmdb_base_url}/search/movie"
        params = {"api_key": self.tmdb_api_key, "query": title}
        if year:
            params["year"] = str(year)

        try:
            async with httpx.AsyncClient(**self._tmdb_client_kwargs()) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning("TMDb search non-200", status=resp.status_code, title=title)
                    return None

                results = resp.json().get("results", [])
                if not results:
                    logger.warning("TMDb no results", title=title, year=year)
                    return None

                first = results[0]
                movie_id = first.get("id")
                details = first
                if movie_id:
                    details_resp = await client.get(
                        f"{self.tmdb_base_url}/movie/{movie_id}",
                        params={"api_key": self.tmdb_api_key},
                    )
                    if details_resp.status_code == 200:
                        details = details_resp.json()

                resolved_year = year
                rel_date = details.get("release_date")
                if not resolved_year and rel_date and len(str(rel_date)) >= 4:
                    try:
                        resolved_year = int(str(rel_date)[:4])
                    except (ValueError, TypeError):
                        resolved_year = None

                poster_path = details.get("poster_path")
                backdrop_path = details.get("backdrop_path")
                return {
                    "provider": "tmdb",
                    "title": details.get("title") or title,
                    "original_title": details.get("original_title"),
                    "year": resolved_year,
                    "tmdb_id": details.get("id") or movie_id,
                    "imdb_id": details.get("imdb_id"),
                    "overview": details.get("overview"),
                    "rating_tmdb": details.get("vote_average"),
                    "rating_imdb": None,
                    "poster_url": (
                        f"{self.tmdb_image_base_url}/w500{poster_path}" if poster_path else None
                    ),
                    "backdrop_url": (
                        f"{self.tmdb_image_base_url}/w1280{backdrop_path}" if backdrop_path else None
                    ),
                }
        except Exception as exc:
            logger.warning("TMDb query failed (blocked or unreachable?)", error=str(exc), title=title)
            return None

    async def _query_omdb_movie(self, title: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
        """OMDb (IMDb data). Usually reachable from India when TMDb is not."""
        if not self.omdb_api_key:
            logger.info("OMDb skipped (OMDB_API_KEY empty)")
            return None

        params: Dict[str, str] = {
            "apikey": self.omdb_api_key,
            "type": "movie",
            "r": "json",
            "t": title,
        }
        if year:
            params["y"] = str(year)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(self.omdb_base_url, params=params)
                if resp.status_code != 200:
                    logger.warning("OMDb non-200", status=resp.status_code, title=title)
                    return None

                data = resp.json()
                if str(data.get("Response", "")).lower() != "true":
                    # Title match missed — try search endpoint
                    search_params = {
                        "apikey": self.omdb_api_key,
                        "type": "movie",
                        "r": "json",
                        "s": title,
                    }
                    if year:
                        search_params["y"] = str(year)
                    search_resp = await client.get(self.omdb_base_url, params=search_params)
                    if search_resp.status_code != 200:
                        return None
                    search_data = search_resp.json()
                    if str(search_data.get("Response", "")).lower() != "true":
                        logger.warning("OMDb no results", title=title, year=year, error=data.get("Error"))
                        return None
                    first = (search_data.get("Search") or [None])[0]
                    if not first or not first.get("imdbID"):
                        return None
                    detail_resp = await client.get(
                        self.omdb_base_url,
                        params={
                            "apikey": self.omdb_api_key,
                            "i": first["imdbID"],
                            "r": "json",
                        },
                    )
                    if detail_resp.status_code != 200:
                        return None
                    data = detail_resp.json()
                    if str(data.get("Response", "")).lower() != "true":
                        return None

                poster = data.get("Poster")
                if poster in (None, "", "N/A"):
                    poster = None

                rating_imdb = None
                raw_rating = data.get("imdbRating")
                if raw_rating and raw_rating != "N/A":
                    try:
                        rating_imdb = float(raw_rating)
                    except (ValueError, TypeError):
                        rating_imdb = None

                resolved_year = year
                raw_year = data.get("Year")
                if raw_year and str(raw_year)[:4].isdigit():
                    resolved_year = int(str(raw_year)[:4])

                return {
                    "provider": "omdb",
                    "title": data.get("Title") or title,
                    "original_title": None,
                    "year": resolved_year,
                    "tmdb_id": None,
                    "imdb_id": data.get("imdbID"),
                    "overview": data.get("Plot") if data.get("Plot") != "N/A" else None,
                    "rating_tmdb": None,
                    "rating_imdb": rating_imdb,
                    "poster_url": poster,
                    "backdrop_url": None,
                }
        except Exception as exc:
            logger.warning("OMDb query failed", error=str(exc), title=title)
            return None
