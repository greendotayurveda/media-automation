"""
Health monitoring models: HealthReport, HealthIssue.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base, AuditMixin


class HealthReport(Base, AuditMixin):
    """
    Saves results of system-wide health scans.
    """
    __tablename__ = "health_reports"

    scan_type: Mapped[str] = mapped_column(String(100), default="scheduled")  # scheduled, manual
    issues_found: Mapped[int] = mapped_column(Integer, default=0)
    issues_resolved: Mapped[int] = mapped_column(Integer, default=0)
    execution_time_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    issues: Mapped[List[HealthIssue]] = relationship("HealthIssue", back_populates="report", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<HealthReport issues={self.issues_found} resolved={self.issues_resolved}>"


class HealthIssue(Base, AuditMixin):
    """
    Individual system issue discovered during health scan.
    """
    __tablename__ = "health_issues"

    report_id: Mapped[str] = mapped_column(ForeignKey("health_reports.id", ondelete="CASCADE"), index=True)
    
    # Issue categorization
    category: Mapped[str] = mapped_column(String(100), index=True)  # missing_file, file_corrupt, metadata_missing, subtitle_missing, db_mismatch
    severity: Mapped[str] = mapped_column(String(50), default="warning")  # info, warning, critical
    
    # Context
    description: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    media_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    media_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "movie", "episode"

    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolution_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    report: Mapped[HealthReport] = relationship("HealthReport", back_populates="issues")

    def __repr__(self) -> str:
        return f"<HealthIssue category={self.category} severity={self.severity} resolved={self.is_resolved}>"
