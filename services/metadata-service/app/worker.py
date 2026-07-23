"""
Metadata Service Redis Streams subscriber worker.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.metadata import MetadataFetcher

logger = get_logger("metadata-worker")


class MetadataWorker(EventSubscriber):
    """
    Subscriber processing METADATA_IDENTIFY_REQUESTED stream events.
    """

    stream = StreamName.METADATA
    consumer_name = "identifier"
    events = [EventType.METADATA_IDENTIFY_REQUESTED]

    def __init__(self) -> None:
        super().__init__(service_name="metadata-service")
        self.fetcher = MetadataFetcher()
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
            logger.error("Metadata identify requested without file_path", payload=payload)
            return

        try:
            metadata = await self.fetcher.identify_and_store_movie(file_path, payload)
            await self.publisher.publish(
                event_type=EventType.METADATA_IDENTIFIED,
                payload={**payload, **metadata, "correlation_id": correlation_id},
                source_service="metadata-service",
                correlation_id=correlation_id,
            )
            logger.info(
                "Identified metadata & published event",
                title=metadata["title"],
                correlation_id=correlation_id,
            )
        except Exception as exc:
            logger.warning(
                "Metadata identification failed; storing fallback movie",
                error=str(exc),
                correlation_id=correlation_id,
            )
            try:
                fallback = await self.fetcher.store_fallback_movie(file_path, payload)
                await self.publisher.publish(
                    event_type=EventType.METADATA_IDENTIFIED,
                    payload={**payload, **fallback, "correlation_id": correlation_id},
                    source_service="metadata-service",
                    correlation_id=correlation_id,
                )
            except Exception as fallback_exc:
                logger.error(
                    "Fallback movie store failed; publishing METADATA_IDENTIFY_FAILED",
                    error=str(fallback_exc),
                    correlation_id=correlation_id,
                )
                await self.publisher.publish(
                    event_type=EventType.METADATA_IDENTIFY_FAILED,
                    payload={
                        **payload,
                        "file_path": file_path,
                        "error": str(exc),
                        "fallback_error": str(fallback_exc),
                        "correlation_id": correlation_id,
                    },
                    source_service="metadata-service",
                    correlation_id=correlation_id,
                )
