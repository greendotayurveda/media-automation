"""
Download Service Redis Streams subscriber worker.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.downloader import Downloader

logger = get_logger("download-worker")


class DownloadWorker(EventSubscriber):
    """
    Subscriber processing DOWNLOAD_QUEUED on StreamName.DOWNLOADS.
    """

    stream = StreamName.DOWNLOADS
    consumer_name = "fetcher"
    events = [EventType.DOWNLOAD_QUEUED]

    def __init__(self) -> None:
        super().__init__(service_name="download-service")
        self.downloader = Downloader()
        self.publisher = EventPublisher(StreamName.WORKFLOWS)
        self.downloads_bus = EventPublisher(StreamName.DOWNLOADS)

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        correlation_id = payload.get("correlation_id") or raw_event.get("correlation_id")
        logger.info("Download queued", correlation_id=correlation_id, payload_keys=list(payload.keys()))

        await self.publisher.publish(
            event_type=EventType.DOWNLOAD_STARTED,
            payload={**payload, "correlation_id": correlation_id},
            source_service="download-service",
            correlation_id=correlation_id,
        )
        await self.downloads_bus.publish(
            event_type=EventType.DOWNLOAD_STARTED,
            payload={**payload, "correlation_id": correlation_id},
            source_service="download-service",
            correlation_id=correlation_id,
        )

        try:
            result = await self.downloader.process(payload)
            merged = {**payload, **result, "correlation_id": correlation_id}
            await self.publisher.publish(
                event_type=EventType.DOWNLOAD_COMPLETED,
                payload=merged,
                source_service="download-service",
                correlation_id=correlation_id,
            )
            await self.downloads_bus.publish(
                event_type=EventType.DOWNLOAD_COMPLETED,
                payload=merged,
                source_service="download-service",
                correlation_id=correlation_id,
            )
            logger.info(
                "Download completed & published",
                download_id=result.get("download_id"),
                dest=result.get("dest_path"),
                correlation_id=correlation_id,
            )
        except Exception as exc:
            fail_payload = {
                **payload,
                "correlation_id": correlation_id,
                "error": str(exc),
                "status": "failed",
            }
            await self.publisher.publish(
                event_type=EventType.DOWNLOAD_FAILED,
                payload=fail_payload,
                source_service="download-service",
                correlation_id=correlation_id,
            )
            await self.downloads_bus.publish(
                event_type=EventType.DOWNLOAD_FAILED,
                payload=fail_payload,
                source_service="download-service",
                correlation_id=correlation_id,
            )
            raise
