"""
TMDb API client and title/year regex parser.
Identifies media metadata and saves record into PostgreSQL.
"""
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.exceptions.base import MetadataError
from shared.logging.logger import get_logger

logger = get_logger("metadata-service")


class MetadataFetcher:
    """
    Parses media filenames and queries TMDb API for metadata enrichment.
    """

    def __init__(self) -> None:
        self.api_key = settings.tmdb_api_key
        self.base_url = settings.tmdb_base_url

    def parse_filename(self, filename: str) -> Tuple[str, Optional[int]]:
        """Clean scene/release tags from filename to extract clean title and year."""
        clean_name = Path(filename).stem
        clean_name = clean_name.replace(".", " ").replace("_", " ")

        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", clean_name)
        year = int(year_match.group(1)) if year_match else None

        if year_match:
            clean_name = clean_name[: year_match.start()].strip()

        clean_name = re.sub(
            r"\b(1080p|2160p|720p|480p|bluray|webrip|web-dl|hdrip|x264|x265|hevc|h264|aac|dts)\b",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip()

        return clean_name, year

    async def identify_and_store_movie(self, file_path: str, payload_specs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query TMDb and upsert Movie by tmdb_id/imdb_id so upgrades reuse the same row.
        Incoming download path is returned as file_path; library path is preserved separately.
        """
        file_name = Path(file_path).name
        clean_title, year = self.parse_filename(file_name)

        tmdb_data = await self._query_tmdb_movie(clean_title, year)
        imdb_id = tmdb_data.get("imdb_id")
        tmdb_id = tmdb_data.get("id")
        resolved_title = tmdb_data.get("title") or clean_title
        resolved_year = year
        rel_date = tmdb_data.get("release_date")
        if not resolved_year and rel_date and len(str(rel_date)) >= 4:
            try:
                resolved_year = int(str(rel_date)[:4])
            except (ValueError, TypeError):
                resolved_year = None

        async with get_db_session() as db:
            movie = await self._find_existing_movie(db, tmdb_id=tmdb_id, imdb_id=imdb_id)
            existing_library_path = None
            is_update = movie is not None

            if movie:
                # Keep current library path for quality upgrade comparisons.
                if movie.file_path and self._is_library_path(movie.file_path):
                    existing_library_path = movie.file_path

                movie.title = resolved_title
                movie.original_title = tmdb_data.get("original_title") or movie.original_title
                movie.year = resolved_year or movie.year
                movie.tmdb_id = tmdb_id or movie.tmdb_id
                movie.imdb_id = imdb_id or movie.imdb_id
                movie.overview = tmdb_data.get("overview") or movie.overview
                movie.rating_tmdb = tmdb_data.get("vote_average") or movie.rating_tmdb
                if tmdb_data.get("poster_path"):
                    movie.poster_url = f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}"
                if tmdb_data.get("backdrop_path"):
                    movie.backdrop_url = f"https://image.tmdb.org/t/p/w1280{tmdb_data.get('backdrop_path')}"
                # Do not overwrite library file_path with the incoming download path.
            else:
                movie = Movie(
                    title=resolved_title,
                    original_title=tmdb_data.get("original_title"),
                    year=resolved_year,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    overview=tmdb_data.get("overview"),
                    rating_tmdb=tmdb_data.get("vote_average"),
                    poster_url=(
                        f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}"
                        if tmdb_data.get("poster_path")
                        else None
                    ),
                    backdrop_url=(
                        f"https://image.tmdb.org/t/p/w1280{tmdb_data.get('backdrop_path')}"
                        if tmdb_data.get("backdrop_path")
                        else None
                    ),
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

    async def _query_tmdb_movie(self, title: str, year: Optional[int]) -> Dict[str, Any]:
        """Perform HTTP call to TMDb search API, then enrich with movie details (imdb_id)."""
        if not self.api_key:
            logger.warning("TMDB_API_KEY is missing. Using fallback metadata parsing.")
            return {"title": title, "release_date": f"{year}-01-01" if year else None}

        url = f"{self.base_url}/search/movie"
        params = {"api_key": self.api_key, "query": title}
        if year:
            params["year"] = str(year)

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning("TMDb search returned non-200 status, falling back to parsed filename title", status=resp.status_code, title=title)
                    return {"title": title, "release_date": f"{year}-01-01" if year else None}

                results = resp.json().get("results", [])
                if not results:
                    logger.warning("No TMDb results found for title, using parsed title", title=title, year=year)
                    return {"title": title, "release_date": f"{year}-01-01" if year else None}

                first = results[0]
                movie_id = first.get("id")
                # Enrich with imdb_id
                details_url = f"{self.base_url}/movie/{movie_id}"
                details_resp = await client.get(details_url, params={"api_key": self.api_key})
                if details_resp.status_code == 200:
                    return details_resp.json()
                return first
            except Exception as exc:
                logger.warning("TMDb query failed, falling back to parsed title", error=str(exc))
                return {"title": title, "release_date": f"{year}-01-01" if year else None}
