"""
Workflow Engine and Platform Event logging models: WorkflowJob, WorkflowStep, PlatformEvent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import ForeignKey, Integer, String, Text, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base, AuditMixin


class WorkflowJob(Base, AuditMixin):
    """
    Orchestrator job tracking a full media processing pipeline.
    """
    __tablename__ = "workflow_jobs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g., "movie_ingestion_pipeline"
    correlation_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)  # pending, running, completed, failed, cancelled
    
    # Context payload
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # Associated media IDs (polymorphic relation pointers or simple UUIDs)
    media_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    media_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # movie, episode

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    steps: Mapped[List[WorkflowStep]] = relationship(
        "WorkflowStep", back_populates="job", cascade="all, delete-orphan", order_by="WorkflowStep.order"
    )

    def __repr__(self) -> str:
        return f"<WorkflowJob {self.name} correlation_id={self.correlation_id} status={self.status}>"


class WorkflowStep(Base, AuditMixin):
    """
    Individual task/step in a workflow job.
    """
    __tablename__ = "workflow_steps"

    job_id: Mapped[str] = mapped_column(ForeignKey("workflow_jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g., "analyze_media", "download_subtitle"
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)  # pending, running, completed, failed, skipped
    order: Mapped[int] = mapped_column(Integer, default=0)

    # Inputs/Outputs/Errors
    input_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    output_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    job: Mapped[WorkflowJob] = relationship("WorkflowJob", back_populates="steps")

    def __repr__(self) -> str:
        return f"<WorkflowStep {self.name} status={self.status} order={self.order}>"


class PlatformEvent(Base):
    """
    Immutable log of every event processed or published across the platform event bus.
    """
    __tablename__ = "platform_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID generated at publish time
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_service: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # Audit log insertion timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<PlatformEvent {self.event_type} correlation_id={self.correlation_id}>"
