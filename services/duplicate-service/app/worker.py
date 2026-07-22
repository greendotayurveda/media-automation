"""
Duplicate Service Redis Streams subscriber worker.

Listens on StreamName.WORKFLOWS for FILE_ORGANIZED (and DUPLICATE_DETECTED for
manual re-resolve). There is no StreamName.DUPLICATES yet — WORKFLOWS is the
post-organize signal that a movie landed in the library.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.duplicates import DuplicateDetector

logger = get_logger("duplicate-worker")


class DuplicateWorker(EventSubscriber):
    """
    After FILE_ORGANIZED, scan that movie for duplicates and auto-resolve.
    """

    stream = StreamName.WORKFLOWS
    consumer_name = "deduper"
    events = [EventType.FILE_ORGANIZED, EventType.DUPLICATE_DETECTED]

    def __init__(self) -> None:
        super().__init__(service_name="duplicate-service")
        self.detector = DuplicateDetector()
        self.publisher = EventPublisher(StreamName.WORKFLOWS)

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        correlation_id = payload.get("correlation_id") or raw_event.get("correlation_id")

        if event_type == EventType.DUPLICATE_DETECTED:
            duplicate_id = payload.get("duplicate_id") or payload.get("id")
            if not duplicate_id:
                return
            resolved = await self.detector.resolve_duplicate(duplicate_id)
            if resolved:
                await self.publisher.publish(
                    event_type=EventType.DUPLICATE_RESOLVED,
                    payload={**payload, **resolved, "correlation_id": correlation_id},
                    source_service="duplicate-service",
                    correlation_id=correlation_id,
                )
            return

        movie_id = payload.get("movie_id")
        if not movie_id:
            logger.warning("FILE_ORGANIZED without movie_id — skipping duplicate check")
            return

        logger.info("Checking duplicates after organize", movie_id=movie_id)
        result = await self.detector.check_for_movie(movie_id)

        for detected in result.get("detected", []):
            await self.publisher.publish(
                event_type=EventType.DUPLICATE_DETECTED,
                payload={**detected, "correlation_id": correlation_id},
                source_service="duplicate-service",
                correlation_id=correlation_id,
            )

        for resolved in result.get("resolved", []):
            await self.publisher.publish(
                event_type=EventType.DUPLICATE_RESOLVED,
                payload={**resolved, "correlation_id": correlation_id},
                source_service="duplicate-service",
                correlation_id=correlation_id,
            )

        logger.info(
            "Duplicate check complete",
            movie_id=movie_id,
            detected=len(result.get("detected", [])),
            resolved=len(result.get("resolved", [])),
            correlation_id=correlation_id,
        )
