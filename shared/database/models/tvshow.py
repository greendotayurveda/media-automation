"""
TV Show-related models: TvShow, Season, Episode.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from sqlalchemy import (
    BigInteger, ForeignKey, Float, Integer, String, Text, Date, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base, AuditMixin, SoftDeleteMixin


class TvShow(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "tv_shows"

    # External IDs
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)

    # Metadata
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    original_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    first_air_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="returning series")

    # Ratings
    rating_tmdb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rating_imdb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Artwork
    poster_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    backdrop_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    poster_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    backdrop_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # File System mapping
    folder_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)

    # Relationships
    seasons: Mapped[List[Season]] = relationship("Season", back_populates="tv_show", cascade="all, delete-orphan")
    episodes: Mapped[List[Episode]] = relationship("Episode", back_populates="tv_show", cascade="all, delete-orphan")
    genres: Mapped[List[Genre]] = relationship("Genre", secondary="tv_show_genres", back_populates="tv_shows")

    def __repr__(self) -> str:
        return f"<TvShow {self.title}>"


class TvShowGenre(Base):
    __tablename__ = "tv_show_genres"
    __table_args__ = (UniqueConstraint("tv_show_id", "genre_id"),)

    tv_show_id: Mapped[str] = mapped_column(ForeignKey("tv_shows.id", ondelete="CASCADE"), primary_key=True)
    genre_id: Mapped[str] = mapped_column(ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True)


# Add relationship in Genre if not already done, but Genre is already defined in movie.py. 
# We'll need to define Genre relationship in movie.py or resolve cross-relations.
# We'll make sure Genre has the back_populates dynamically or mapped properly.
# To keep models decoupled, we declare relationships carefully.

class Season(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("tv_show_id", "season_number"),)

    tv_show_id: Mapped[str] = mapped_column(ForeignKey("tv_shows.id", ondelete="CASCADE"), index=True)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Metadata
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    air_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    poster_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)

    # Relationships
    tv_show: Mapped[TvShow] = relationship("TvShow", back_populates="seasons")
    episodes: Mapped[List[Episode]] = relationship("Episode", back_populates="season", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Season {self.season_number} of show_id={self.tv_show_id}>"


class Episode(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("season_id", "episode_number"),)

    tv_show_id: Mapped[str] = mapped_column(ForeignKey("tv_shows.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[str] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Metadata
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    air_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    runtime_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating_tmdb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True, index=True)

    # File Info
    file_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Relationships
    tv_show: Mapped[TvShow] = relationship("TvShow", back_populates="episodes")
    season: Mapped[Season] = relationship("Season", back_populates="episodes")
    subtitles: Mapped[List[Subtitle]] = relationship("Subtitle", back_populates="episode")
    quality: Mapped[List[MediaQuality]] = relationship("MediaQuality", back_populates="episode")

    def __repr__(self) -> str:
        return f"<Episode S{self.season_number}E{self.episode_number} - {self.title}>"
