"""
Organizer Service Redis Streams subscriber worker.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.organizer import MediaOrganizer

logger = get_logger("organizer-worker")


class OrganizerWorker(EventSubscriber):
    """
    Subscriber processing FILE_ORGANIZE_REQUESTED stream events.
    """

    stream = StreamName.FILES
    consumer_name = "organizer"
    events = [EventType.FILE_ORGANIZE_REQUESTED]

    def __init__(self) -> None:
        super().__init__(service_name="organizer-service")
        self.organizer = MediaOrganizer()
        self.publisher = EventPublisher(StreamName.WORKFLOWS)

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        correlation_id = payload.get("correlation_id") or raw_event.get("correlation_id")

        logger.info("Starting file organization", correlation_id=correlation_id)
        result = await self.organizer.organize_movie(payload)

        await self.publisher.publish(
            event_type=EventType.FILE_ORGANIZED,
            payload={**payload, **result, "correlation_id": correlation_id},
            source_service="organizer-service",
            correlation_id=correlation_id,
        )

        if result.get("upgrade_applied"):
            await self.publisher.publish(
                event_type=EventType.QUALITY_UPGRADED,
                payload={**payload, **result, "correlation_id": correlation_id},
                source_service="organizer-service",
                correlation_id=correlation_id,
            )
            logger.info(
                "Published QUALITY_UPGRADED",
                replaced=result.get("replaced_file_path"),
                archived=result.get("archived_file_path"),
                correlation_id=correlation_id,
            )

        await self.publisher.publish(
            event_type=EventType.JELLYFIN_REFRESHED,
            payload={**payload, **result, "correlation_id": correlation_id},
            source_service="organizer-service",
            correlation_id=correlation_id,
        )
        logger.info("Organized media & published completion events", correlation_id=correlation_id)
