"""
Storage optimization and tracking models: StorageReport.
"""
from __future__ import annotations

from typing import Dict, Any

from sqlalchemy import BigInteger, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base, AuditMixin


class StorageReport(Base, AuditMixin):
    """
    Tracks disk utilization snapshots over time.
    """
    __tablename__ = "storage_reports"

    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    free_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Detailed statistics by folders (e.g. downloads, movies, tvshows, temp)
    breakdown: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    def __repr__(self) -> str:
        free_gb = round(self.free_bytes / (1024 ** 3), 2)
        total_gb = round(self.total_bytes / (1024 ** 3), 2)
        return f"<StorageReport free={free_gb}GB total={total_gb}GB>"
