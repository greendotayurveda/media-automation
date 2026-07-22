"""
Ollama-backed AI helpers for recommendations, Q&A, and summaries.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select

from shared.config.settings import settings
from shared.database.connection import get_db_session
from shared.database.models.movie import Movie
from shared.logging.logger import get_logger

logger = get_logger("ai-service")


def _ollama_url() -> str:
    return (
        getattr(settings, "ollama_url", None)
        or os.getenv("OLLAMA_URL")
        or "http://ollama:11434"
    ).rstrip("/")


def _ollama_model() -> str:
    return (
        getattr(settings, "ollama_model", None)
        or os.getenv("OLLAMA_MODEL")
        or "llama3.2"
    )


def _timeout() -> float:
    return float(getattr(settings, "ollama_timeout_seconds", 120) or 120)


class AIAssistant:
    """Thin client around Ollama generate/tags APIs with library context."""

    def __init__(self) -> None:
        self.base_url = _ollama_url()
        self.model = _ollama_model()
        self.cache_dir = settings.cache_root / "ai_summaries"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def list_models(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return data.get("models", [])

    async def health(self) -> Dict[str, Any]:
        try:
            models = await self.list_models()
            return {
                "status": "ok",
                "service": "ai-service",
                "ollama_url": self.base_url,
                "model": self.model,
                "models_available": len(models),
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "service": "ai-service",
                "ollama_url": self.base_url,
                "model": self.model,
                "error": str(exc),
            }

    async def generate(self, prompt: str, *, system: Optional[str] = None) -> str:
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return (data.get("response") or "").strip()

    async def recommend(self, *, limit: int = 5, seed: Optional[str] = None) -> Dict[str, Any]:
        titles = await self._library_titles(limit=80)
        if not titles:
            return {"recommendations": [], "note": "Library is empty"}

        catalog = "\n".join(f"- {t}" for t in titles)
        prompt = (
            "You are a movie recommendation assistant for a personal media library.\n"
            f"Library titles:\n{catalog}\n\n"
            f"Recommend up to {limit} movies from this library"
            + (f" similar to: {seed}" if seed else "")
            + ".\nReply with a JSON array of objects with keys title and reason."
        )
        try:
            raw = await self.generate(prompt)
            recommendations = self._parse_json_list(raw)
        except Exception as exc:
            logger.warning("Ollama recommend failed — using fallback", error=str(exc))
            recommendations = [
                {"title": t, "reason": "From your library"} for t in titles[:limit]
            ]

        return {
            "recommendations": recommendations[:limit],
            "model": self.model,
            "seed": seed,
        }

    async def ask(self, question: str) -> Dict[str, Any]:
        titles = await self._library_titles(limit=120)
        catalog = "\n".join(f"- {t}" for t in titles) if titles else "(empty library)"
        system = (
            "Answer questions about the user's personal media library. "
            "Only reference titles that appear in the catalog when recommending."
        )
        prompt = f"Library catalog:\n{catalog}\n\nQuestion: {question}"
        try:
            answer = await self.generate(prompt, system=system)
        except Exception as exc:
            answer = (
                f"AI backend unavailable ({exc}). "
                f"Your library currently has {len(titles)} titles."
            )
        return {"question": question, "answer": answer, "model": self.model}

    async def summarize(
        self,
        *,
        overview: Optional[str] = None,
        movie_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        if movie_id and not overview:
            async with get_db_session() as db:
                result = await db.execute(select(Movie).where(Movie.id == movie_id))
                movie = result.scalar_one_or_none()
                if movie:
                    overview = movie.overview
                    title = title or movie.title

        if not overview:
            return {"summary": "", "error": "No overview available"}

        cache_key = movie_id or (title or "anon").replace("/", "_")
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("overview") == overview:
                    return cached
            except Exception:
                pass

        prompt = (
            f"Summarize this movie overview in 2-3 concise sentences.\n"
            f"Title: {title or 'Unknown'}\nOverview: {overview}"
        )
        try:
            summary = await self.generate(prompt)
        except Exception as exc:
            summary = overview[:400] + ("…" if len(overview) > 400 else "")
            logger.warning("Summarize fell back to truncation", error=str(exc))

        result = {
            "movie_id": movie_id,
            "title": title,
            "overview": overview,
            "summary": summary,
            "model": self.model,
        }
        try:
            cache_path.write_text(json.dumps(result), encoding="utf-8")
        except Exception:
            pass
        return result

    async def _library_titles(self, limit: int = 100) -> List[str]:
        async with get_db_session() as db:
            result = await db.execute(
                select(Movie)
                .where(Movie.deleted_at.is_(None))
                .order_by(Movie.title)
                .limit(limit)
            )
            movies = list(result.scalars().all())
            return [
                f"{m.title} ({m.year})" if m.year else m.title
                for m in movies
            ]

    @staticmethod
    def _parse_json_list(raw: str) -> List[Dict[str, Any]]:
        text = raw.strip()
        # Extract JSON array if model wrapped it in prose
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
        return [{"title": line.strip("- ").strip(), "reason": ""} for line in raw.splitlines() if line.strip()]
