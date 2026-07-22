"""
Download management models: Download.
Tracks torrent/NZB or HTTP downloads, job statuses, and file info.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base, AuditMixin


class Download(Base, AuditMixin):
    __tablename__ = "downloads"

    # Job tracking
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(100), default="telegram")  # telegram, torrent, usenet, http
    external_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)  # Infohash, Telegram Message ID, Magnet Link, etc.
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True)  # queued, downloading, paused, completed, failed, verifying

    # Progress tracking
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 to 100.0
    download_speed_bps: Mapped[int] = mapped_column(BigInteger, default=0)
    eta_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Local file mapping
    temp_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    dest_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Error details
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<Download {self.title} status={self.status}>"
