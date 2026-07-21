"""
TMDb API client and title/year regex parser.
Identifies media metadata and saves record into PostgreSQL.
"""
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.exceptions.base import MetadataError, MovieNotIdentifiedError
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
        # Replace dots/underscores with spaces
        clean_name = clean_name.replace(".", " ").replace("_", " ")

        # Extract 4-digit year (19xx or 20xx)
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", clean_name)
        year = int(year_match.group(1)) if year_match else None

        if year_match:
            clean_name = clean_name[: year_match.start()].strip()

        # Remove common quality/tag noise
        clean_name = re.sub(
            r"\b(1080p|2160p|720p|480p|bluray|webrip|web-dl|hdrip|x264|x265|hevc|h264|aac|dts)\b",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip()

        return clean_name, year

    async def identify_and_store_movie(self, file_path: str, payload_specs: Dict[str, Any]) -> Dict[str, Any]:
        """Query TMDb for movie, save record in PostgreSQL, and return metadata dict."""
        file_name = Path(file_path).name
        clean_title, year = self.parse_filename(file_name)

        tmdb_data = await self._query_tmdb_movie(clean_title, year)
        
        # Save or update Movie in PostgreSQL
        async with get_db_session() as db:
            movie = Movie(
                title=tmdb_data.get("title") or clean_title,
                original_title=tmdb_data.get("original_title"),
                year=year or (int(tmdb_data["release_date"][:4]) if tmdb_data.get("release_date") else None),
                tmdb_id=tmdb_data.get("id"),
                overview=tmdb_data.get("overview"),
                rating_tmdb=tmdb_data.get("vote_average"),
                poster_url=f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}" if tmdb_data.get("poster_path") else None,
                backdrop_url=f"https://image.tmdb.org/t/p/w1280{tmdb_data.get('backdrop_path')}" if tmdb_data.get("backdrop_path") else None,
                file_path=file_path,
                file_size_bytes=payload_specs.get("file_size_bytes"),
            )
            db.add(movie)
            await db.commit()
            await db.refresh(movie)

            logger.info("Saved movie metadata to DB", movie_id=movie.id, title=movie.title)

            return {
                "movie_id": movie.id,
                "title": movie.title,
                "year": movie.year,
                "tmdb_id": movie.tmdb_id,
                "poster_url": movie.poster_url,
                "backdrop_url": movie.backdrop_url,
                "file_path": file_path,
            }

    async def _query_tmdb_movie(self, title: str, year: Optional[int]) -> Dict[str, Any]:
        """Perform HTTP call to TMDb search API."""
        if not self.api_key:
            logger.warning("TMDB_API_KEY is missing. Using fallback metadata parsing.")
            return {"title": title, "release_date": f"{year}-01-01" if year else None}

        url = f"{self.base_url}/search/movie"
        params = {"api_key": self.api_key, "query": title}
        if year:
            params["year"] = str(year)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                raise MetadataError(f"TMDb search failed status={resp.status_code}")

            results = resp.json().get("results", [])
            if not results:
                logger.warning("No TMDb results found for title", title=title, year=year)
                return {"title": title, "release_date": f"{year}-01-01" if year else None}

            return results[0]  # Top search match
