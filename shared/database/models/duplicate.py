"""
Deduplication management models: Duplicate.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, BigInteger, Float
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base, AuditMixin


class Duplicate(Base, AuditMixin):
    """
    Identified duplicate files for a specific movie or episode.
    Allows easy deduplication decisions.
    """
    __tablename__ = "duplicates"

    # Associated media identifier
    media_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)  # Movie or Episode UUID
    media_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "movie" or "episode"

    # Details of primary (to keep) vs duplicate (candidate to delete)
    primary_file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    duplicate_file_path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    
    # Comparison criteria
    reason: Mapped[str] = mapped_column(String(255), default="identical_metadata")  # identical_metadata, smaller_bitrate, worse_codec
    similarity_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    # File sizes
    primary_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duplicate_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    # Resolution details for quick decision
    primary_resolution: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duplicate_resolution: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="detected")  # detected, resolved_keep_primary, resolved_keep_duplicate, ignored

    def __repr__(self) -> str:
        return f"<Duplicate media_id={self.media_id} reason={self.reason} status={self.status}>"
