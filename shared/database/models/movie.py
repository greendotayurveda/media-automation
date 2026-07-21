"""
Movie-related models: Movie, Genre, Person, Studio, Collection.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base, AuditMixin, SoftDeleteMixin


# ─────────────────────────────────────────────────────────────
# Association tables (many-to-many)
# ─────────────────────────────────────────────────────────────

class MovieGenre(Base):
    __tablename__ = "movie_genres"
    __table_args__ = (UniqueConstraint("movie_id", "genre_id"),)

    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True)


class MovieStudio(Base):
    __tablename__ = "movie_studios"
    __table_args__ = (UniqueConstraint("movie_id", "studio_id"),)

    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    studio_id: Mapped[str] = mapped_column(ForeignKey("studios.id", ondelete="CASCADE"), primary_key=True)


class MoviePerson(Base):
    """Links movies to people (cast & crew)."""
    __tablename__ = "movie_people"

    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(50), primary_key=True)  # actor, director, writer, etc.
    character_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)  # billing order


# ─────────────────────────────────────────────────────────────
# Core tables
# ─────────────────────────────────────────────────────────────

class Genre(Base, AuditMixin):
    __tablename__ = "genres"

    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    movies: Mapped[List["Movie"]] = relationship("Movie", secondary="movie_genres", back_populates="genres")
    tv_shows: Mapped[List["TvShow"]] = relationship("TvShow", secondary="tv_show_genres", back_populates="genres")

    def __repr__(self) -> str:
        return f"<Genre {self.name}>"


class Person(Base, AuditMixin):
    __tablename__ = "people"

    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    biography: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    birthday: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    profile_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:
        return f"<Person {self.name}>"


class Studio(Base, AuditMixin):
    __tablename__ = "studios"

    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    def __repr__(self) -> str:
        return f"<Studio {self.name}>"


class Collection(Base, AuditMixin):
    __tablename__ = "collections"

    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    poster_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    backdrop_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    movies: Mapped[List["Movie"]] = relationship("Movie", back_populates="collection")

    def __repr__(self) -> str:
        return f"<Collection {self.name}>"


class Movie(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "movies"

    # External IDs
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)

    # Metadata
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    original_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    runtime_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tagline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="released")

    # Ratings
    rating_tmdb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rating_imdb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vote_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Artwork (local paths)
    poster_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    backdrop_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    poster_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    backdrop_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # File info
    file_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    folder_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)

    # Relations
    collection_id: Mapped[Optional[str]] = mapped_column(ForeignKey("collections.id"), nullable=True)
    collection: Mapped[Optional["Collection"]] = relationship("Collection", back_populates="movies")
    genres: Mapped[List["Genre"]] = relationship("Genre", secondary="movie_genres", back_populates="movies")
    studios: Mapped[List["Studio"]] = relationship("Studio", secondary="movie_studios")
    subtitles: Mapped[List["Subtitle"]] = relationship("Subtitle", back_populates="movie")
    quality: Mapped[List["MediaQuality"]] = relationship("MediaQuality", back_populates="movie")

    def __repr__(self) -> str:
        return f"<Movie {self.title} ({self.year})>"
