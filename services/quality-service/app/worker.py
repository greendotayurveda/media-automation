"""
Quality Service Redis Streams subscriber worker.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from shared.utils.file import archive_file
from app.quality import QualityAssessor

logger = get_logger("quality-worker")


class QualityWorker(EventSubscriber):
    """
    Subscriber processing QUALITY_CHECK_REQUESTED stream events.
    """

    stream = StreamName.QUALITY
    consumer_name = "assessor"
    events = [EventType.QUALITY_CHECK_REQUESTED]

    def __init__(self) -> None:
        super().__init__(service_name="quality-service")
        self.assessor = QualityAssessor()
        self.publisher = EventPublisher(StreamName.WORKFLOWS)

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        correlation_id = payload.get("correlation_id") or raw_event.get("correlation_id")
        logger.info("Starting quality check", correlation_id=correlation_id)

        result = await self.assessor.check_quality(payload)
        merged = {**payload, **result, "correlation_id": correlation_id}

        if result.get("decision") == "keep_existing":
            discarded = self._archive_inferior_download(merged)
            merged["inferior_discarded"] = discarded

        await self.publisher.publish(
            event_type=EventType.QUALITY_CHECKED,
            payload=merged,
            source_service="quality-service",
            correlation_id=correlation_id,
        )

        if result.get("upgrade_available"):
            await self.publisher.publish(
                event_type=EventType.QUALITY_UPGRADE_AVAILABLE,
                payload=merged,
                source_service="quality-service",
                correlation_id=correlation_id,
            )

        logger.info(
            "Completed quality check & published event",
            decision=result.get("decision"),
            correlation_id=correlation_id,
        )

    @staticmethod
    def _archive_inferior_download(payload: Dict[str, Any]) -> bool:
        """Move rejected download out of incoming so it does not waste primary storage."""
        src = payload.get("file_path")
        library = payload.get("existing_library_path")
        if not src:
            return False
        src_path = Path(src)
        if not src_path.exists():
            return False
        try:
            if library and Path(library).resolve() == src_path.resolve():
                return False
        except OSError:
            pass
        if str(settings.library_root) in str(src_path):
            return False
        try:
            archive_dir = settings.temp_root / "rejected" / datetime.now(timezone.utc).strftime("%Y%m%d")
            archived = archive_file(src_path, archive_dir)
            logger.info("Archived inferior download", src=src, archived=archived)
            return True
        except Exception as exc:
            logger.warning("Failed to archive inferior download", src=src, error=str(exc))
            return False
