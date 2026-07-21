"""
Subtitle management models: Subtitle.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base, AuditMixin


class Subtitle(Base, AuditMixin):
    """
    Subtitles tracked for movies or specific episodes.
    """
    __tablename__ = "subtitles"

    # Targets (polymorphic-like foreign keys)
    movie_id: Mapped[Optional[str]] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=True, index=True)
    episode_id: Mapped[Optional[str]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True)

    # Subtitle details
    language: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # eng, mal, tam, etc.
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), default="local")  # opensubtitles, subdl, local
    provider_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # ID from opensubtitles/subdl
    
    # Flags
    is_forced: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hearing_impaired: Mapped[bool] = mapped_column(Boolean, default=False)
    is_synced: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    movie: Mapped[Optional[Movie]] = relationship("Movie", back_populates="subtitles")
    episode: Mapped[Optional[Episode]] = relationship("Episode", back_populates="subtitles")

    def __repr__(self) -> str:
        target = f"movie_id={self.movie_id}" if self.movie_id else f"episode_id={self.episode_id}"
        return f"<Subtitle {target} language={self.language} path={self.file_path}>"
