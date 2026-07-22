"""
Subtitle Service Redis Streams subscriber worker.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.subtitles import SubtitleManager

logger = get_logger("subtitle-worker")


class SubtitleWorker(EventSubscriber):
    """
    Subscriber processing SUBTITLE_SEARCH_REQUESTED stream events.
    """

    stream = StreamName.SUBTITLES
    consumer_name = "fetcher"
    events = [EventType.SUBTITLE_SEARCH_REQUESTED]

    def __init__(self) -> None:
        super().__init__(service_name="subtitle-service")
        self.manager = SubtitleManager()
        self.publisher = EventPublisher(StreamName.WORKFLOWS)

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        file_path = payload.get("file_path")
        correlation_id = payload.get("correlation_id") or raw_event.get("correlation_id")

        if not file_path:
            logger.error("Subtitle search requested without file_path", payload=payload)
            return

        logger.info("Starting subtitle processing", file=file_path, correlation_id=correlation_id)
        result = await self.manager.fetch_and_normalize_subtitles(payload)

        # Pipeline advances on either outcome (workflow handles both events).
        if result.get("subtitles_count", 0) > 0:
            out_event = EventType.SUBTITLE_DOWNLOADED
        else:
            out_event = EventType.SUBTITLE_NOT_FOUND

        await self.publisher.publish(
            event_type=out_event,
            payload={**payload, **result, "correlation_id": correlation_id},
            source_service="subtitle-service",
            correlation_id=correlation_id,
        )
        logger.info(
            "Completed subtitle processing & published event",
            event_type=out_event.value,
            count=result.get("subtitles_count", 0),
            missing=result.get("languages_missing"),
            correlation_id=correlation_id,
        )
