"""
IPTV, Radio, and Streaming Recording models: IptvChannel, RadioStation, Recording.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base, AuditMixin


class IptvChannel(Base, AuditMixin):
    """
    IPTV streams imported from M3U/M3U8 playlists.
    """
    __tablename__ = "iptv_channels"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    stream_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    
    # Metadata
    logo_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    group_name: Mapped[Optional[str]] = mapped_column(String(100), index=True)  # Channel category
    epg_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # EPG matching key

    # States
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    def __repr__(self) -> str:
        return f"<IptvChannel {self.name} group={self.group_name}>"


class RadioStation(Base, AuditMixin):
    """
    Online radio station streams.
    """
    __tablename__ = "radio_stations"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    stream_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    
    # Metadata
    logo_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    country: Mapped[Optional[str]] = mapped_column(String(50), index=True)

    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    def __repr__(self) -> str:
        return f"<RadioStation {self.name} genre={self.genre}>"


class Recording(Base, AuditMixin):
    """
    Live TV or Radio stream recordings.
    """
    __tablename__ = "recordings"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50))  # iptv, radio
    source_id: Mapped[str] = mapped_column(String(36))  # IptvChannel or RadioStation UUID
    
    # Recording Details
    file_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="scheduled")  # scheduled, recording, completed, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Schedule
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Recording {self.title} status={self.status}>"
