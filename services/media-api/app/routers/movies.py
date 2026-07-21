"""
FastAPI router for Movies library endpoints (/api/v1/movies).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.connection import get_db
from shared.database.models.movie import Movie

router = APIRouter(prefix="/api/v1/movies", tags=["Movies"])


class MovieResponse(BaseModel):
    id: str
    title: str
    year: Optional[int] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    overview: Optional[str] = None
    poster_path: Optional[str] = None
    file_path: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[MovieResponse])
async def list_movies(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List movies with pagination and optional title search."""
    query = select(Movie).where(Movie.deleted_at.is_(None))
    if search:
        query = query.where(Movie.title.ilike(f"%{search}%"))
    query = query.order_by(Movie.title).offset(skip).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{movie_id}", response_model=MovieResponse)
async def get_movie(movie_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific movie by ID."""
    result = await db.execute(select(Movie).where(Movie.id == movie_id, Movie.deleted_at.is_(None)))
    movie = result.scalar_one_or_none()
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie
