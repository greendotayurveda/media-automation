"""
Workflow Engine state machine and pipeline orchestrator.
Manages workflow jobs, step execution transitions, and database state.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.connection import get_db_session
from shared.database.models.workflow import WorkflowJob, WorkflowStep, PlatformEvent
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.logging.logger import get_logger

logger = get_logger("workflow-engine")


class WorkflowOrchestrator:
    """
    State machine that drives media processing pipelines.
    """

    def __init__(self) -> None:
        self.media_publisher = EventPublisher(StreamName.MEDIA)
        self.metadata_publisher = EventPublisher(StreamName.METADATA)
        self.subtitle_publisher = EventPublisher(StreamName.SUBTITLES)
        self.quality_publisher = EventPublisher(StreamName.QUALITY)
        self.file_publisher = EventPublisher(StreamName.FILES)
        self.notification_publisher = EventPublisher(StreamName.NOTIFICATIONS)

    async def start_movie_pipeline(
        self,
        correlation_id: str,
        file_path: str,
        source: str = "telegram",
    ) -> str:
        """
        Initiate a new movie ingestion workflow pipeline.
        """
        async with get_db_session() as db:
            # Create workflow job
            job = WorkflowJob(
                name="movie_ingestion_pipeline",
                correlation_id=correlation_id,
                status="running",
                payload={"file_path": file_path, "source": source},
                started_at=datetime.now(timezone.utc),
            )
            db.add(job)
            await db.flush()

            # Create initial steps
            steps = [
                WorkflowStep(job_id=job.id, name="analyze_media", order=1, status="pending"),
                WorkflowStep(job_id=job.id, name="identify_metadata", order=2, status="pending"),
                WorkflowStep(job_id=job.id, name="download_subtitles", order=3, status="pending"),
                WorkflowStep(job_id=job.id, name="verify_quality", order=4, status="pending"),
                WorkflowStep(job_id=job.id, name="organize_file", order=5, status="pending"),
                WorkflowStep(job_id=job.id, name="refresh_jellyfin", order=6, status="pending"),
            ]
            db.add_all(steps)
            await db.commit()

            logger.info("Started movie pipeline", job_id=job.id, correlation_id=correlation_id)

        # Trigger Step 1: Request Media Analysis
        await self.media_publisher.publish(
            event_type=EventType.MEDIA_ANALYZE_REQUESTED,
            payload={"file_path": file_path, "correlation_id": correlation_id},
            source_service="workflow-engine",
            correlation_id=correlation_id,
        )

        return correlation_id

    async def handle_event(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_fields: Dict[str, str],
    ) -> None:
        """
        Main handler for incoming stream events — advances pipeline state.
        """
        correlation_id = payload.get("correlation_id") or raw_fields.get("correlation_id")
        if not correlation_id:
            logger.warning("Event missing correlation_id, ignoring pipeline advancement", event_type=event_type.value)
            return

        # Audit event into platform_events table
        await self._log_platform_event(raw_fields)

        # Pipeline state transition logic
        if event_type == EventType.MOVIE_RECEIVED or event_type == EventType.DOWNLOAD_COMPLETED:
            file_path = payload.get("file_path") or payload.get("dest_path")
            if file_path:
                await self.start_movie_pipeline(correlation_id=correlation_id, file_path=file_path)

        elif event_type == EventType.MEDIA_ANALYZED:
            await self._complete_step_and_trigger_next(
                correlation_id=correlation_id,
                completed_step_name="analyze_media",
                next_event_type=EventType.METADATA_IDENTIFY_REQUESTED,
                next_publisher=self.metadata_publisher,
                output_payload=payload,
            )

        elif event_type == EventType.METADATA_IDENTIFIED:
            await self._complete_step_and_trigger_next(
                correlation_id=correlation_id,
                completed_step_name="identify_metadata",
                next_event_type=EventType.SUBTITLE_SEARCH_REQUESTED,
                next_publisher=self.subtitle_publisher,
                output_payload=payload,
            )

        elif event_type == EventType.SUBTITLE_DOWNLOADED or event_type == EventType.SUBTITLE_NOT_FOUND:
            await self._complete_step_and_trigger_next(
                correlation_id=correlation_id,
                completed_step_name="download_subtitles",
                next_event_type=EventType.QUALITY_CHECK_REQUESTED,
                next_publisher=self.quality_publisher,
                output_payload=payload,
            )

        elif event_type == EventType.QUALITY_CHECKED:
            await self._complete_step_and_trigger_next(
                correlation_id=correlation_id,
                completed_step_name="verify_quality",
                next_event_type=EventType.FILE_ORGANIZE_REQUESTED,
                next_publisher=self.file_publisher,
                output_payload=payload,
            )

        elif event_type == EventType.FILE_ORGANIZED:
            await self._complete_step_and_trigger_next(
                correlation_id=correlation_id,
                completed_step_name="organize_file",
                next_event_type=EventType.JELLYFIN_REFRESH_REQUESTED,
                next_publisher=self.notification_publisher,
                output_payload=payload,
            )

        elif event_type == EventType.JELLYFIN_REFRESHED:
            await self._finalize_workflow(correlation_id=correlation_id, status="completed")

        elif "failed" in event_type.value:
            await self._finalize_workflow(correlation_id=correlation_id, status="failed", error_details=payload)

    async def _complete_step_and_trigger_next(
        self,
        correlation_id: str,
        completed_step_name: str,
        next_event_type: EventType,
        next_publisher: EventPublisher,
        output_payload: Dict[str, Any],
    ) -> None:
        """Mark a step as completed and publish the event for the next stage."""
        async with get_db_session() as db:
            result = await db.execute(
                select(WorkflowJob).where(WorkflowJob.correlation_id == correlation_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                logger.warning("No workflow job found for correlation_id", correlation_id=correlation_id)
                return

            # Update completed step
            step_result = await db.execute(
                select(WorkflowStep).where(
                    WorkflowStep.job_id == job.id,
                    WorkflowStep.name == completed_step_name,
                )
            )
            step = step_result.scalar_one_or_none()
            if step:
                step.status = "completed"
                step.output_data = output_payload
                step.completed_at = datetime.now(timezone.utc)
                await db.commit()

        # Publish next stage event
        await next_publisher.publish(
            event_type=next_event_type,
            payload={**output_payload, "correlation_id": correlation_id},
            source_service="workflow-engine",
            correlation_id=correlation_id,
        )

    async def _finalize_workflow(
        self, correlation_id: str, status: str, error_details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Mark workflow as completed or failed."""
        async with get_db_session() as db:
            result = await db.execute(
                select(WorkflowJob).where(WorkflowJob.correlation_id == correlation_id)
            )
            job = result.scalar_one_or_none()
            if job:
                job.status = status
                job.completed_at = datetime.now(timezone.utc)
                if error_details:
                    job.payload["error"] = error_details
                await db.commit()
                logger.info("Finalized workflow job", job_id=job.id, status=status)

    async def _log_platform_event(self, raw_fields: Dict[str, str]) -> None:
        """Persist every event to the platform_events table."""
        try:
            event_id = raw_fields.get("event_id", str(uuid.uuid4()))
            async with get_db_session() as db:
                event = PlatformEvent(
                    id=event_id,
                    event_type=raw_fields.get("event_type", "unknown"),
                    correlation_id=raw_fields.get("correlation_id", "none"),
                    source_service=raw_fields.get("source_service", "unknown"),
                    published_at=datetime.now(timezone.utc),
                    payload=raw_fields,
                )
                db.add(event)
                await db.commit()
        except Exception as exc:
            logger.error("Failed to log platform event to DB", error=str(exc))
