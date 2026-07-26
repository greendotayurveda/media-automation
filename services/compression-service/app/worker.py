"""
Compression Service Redis Streams subscriber worker.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.compressor import MediaCompressor

logger = get_logger("compression-worker")


class CompressionWorker(EventSubscriber):
    """
    Subscriber listening to stream:compression for MEDIA_COMPRESS_REQUESTED.
    """

    stream = StreamName.COMPRESSION
    consumer_name = "encoder"
    events = [EventType.MEDIA_COMPRESS_REQUESTED]

    def __init__(self) -> None:
        super().__init__(service_name="compression-service")
        self.compressor = MediaCompressor()
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
            logger.error("Compression requested without file_path", payload=payload)
            return

        logger.info("Starting compression processing", file=file_path, correlation_id=correlation_id)

        try:
            result = await self.compressor.compress(file_path)
            action = result.get("action", "skipped")

            out_event = (
                EventType.MEDIA_COMPRESSED
                if action == "compressed"
                else EventType.MEDIA_COMPRESS_SKIPPED
            )

            await self.publisher.publish(
                event_type=out_event,
                payload={**payload, **result, "correlation_id": correlation_id},
                source_service="compression-service",
                correlation_id=correlation_id,
            )
            logger.info("Compression job completed & published event", action=action, event=out_event.value, correlation_id=correlation_id)

        except Exception as exc:
            logger.warning("Compression execution failed, publishing MEDIA_COMPRESS_FAILED event to continue pipeline", error=str(exc))
            fail_payload = {
                **payload,
                "file_path": file_path,
                "error": str(exc),
                "correlation_id": correlation_id,
            }
            await self.publisher.publish(
                event_type=EventType.MEDIA_COMPRESS_FAILED,
                payload=fail_payload,
                source_service="compression-service",
                correlation_id=correlation_id,
            )
