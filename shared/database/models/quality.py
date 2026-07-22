"""
Quality management models: MediaQuality, QualityRule.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base, AuditMixin


class MediaQuality(Base, AuditMixin):
    """
    Detailed video/audio quality properties parsed for a movie or episode.
    """
    __tablename__ = "media_qualities"

    # Targets (Polymorphic-like foreign keys)
    movie_id: Mapped[Optional[str]] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=True, index=True)
    episode_id: Mapped[Optional[str]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True)

    # Video properties
    resolution: Mapped[str] = mapped_column(String(50), nullable=False)  # 2160p, 1080p, 720p, etc.
    video_codec: Mapped[str] = mapped_column(String(50), nullable=False)  # hevc, h264, vp9, av1
    bitrate_kbps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_hdr: Mapped[bool] = mapped_column(Boolean, default=False)
    hdr_format: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # HDR10, Dolby Vision, HLG
    frame_rate: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 23.976, 24, 25, 29.97, 50, 60

    # Audio properties
    audio_codec: Mapped[str] = mapped_column(String(50), nullable=False)  # ac3, eac3, dts, truehd, flac, aac
    audio_channels: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 2.0, 5.1, 7.1
    audio_language: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # eng, mal, etc.

    # Container
    container: Mapped[str] = mapped_column(String(50), default="mkv")  # mkv, mp4

    # Relationships
    movie: Mapped[Optional[Movie]] = relationship("Movie", back_populates="quality")
    episode: Mapped[Optional[Episode]] = relationship("Episode", back_populates="quality")

    def __repr__(self) -> str:
        target = f"movie_id={self.movie_id}" if self.movie_id else f"episode_id={self.episode_id}"
        return f"<MediaQuality {target} resolution={self.resolution} codec={self.video_codec}>"


class QualityRule(Base, AuditMixin):
    """
    User settings governing which formats and codecs are preferred or blocked.
    """
    __tablename__ = "quality_rules"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)  # Rule evaluation priority order
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Rule Matchers (JSON or simple matching attributes)
    resolution_preference: Mapped[str] = mapped_column(String(255), default="2160p,1080p,720p")
    preferred_codecs: Mapped[str] = mapped_column(String(255), default="hevc,h264")
    require_hdr: Mapped[bool] = mapped_column(Boolean, default=False)
    max_file_size_gb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<QualityRule {self.name} active={self.is_active}>"
