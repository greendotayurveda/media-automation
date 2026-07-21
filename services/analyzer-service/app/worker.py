"""
Analyzer Service Redis Streams subscriber worker.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.analyzer import MediaAnalyzer

logger = get_logger("analyzer-worker")


class AnalyzerWorker(EventSubscriber):
    """
    Subscriber processing MEDIA_ANALYZE_REQUESTED stream events.
    """

    stream = StreamName.MEDIA
    consumer_name = "analyzer"
    events = [EventType.MEDIA_ANALYZE_REQUESTED]

    def __init__(self) -> None:
        super().__init__(service_name="analyzer-service")
        self.analyzer = MediaAnalyzer()
        self.publisher = EventPublisher(StreamName.WORKFLOWS)

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        """Analyze incoming media file and publish specs back to workflow engine."""
        file_path = payload.get("file_path")
        correlation_id = payload.get("correlation_id") or raw_event.get("correlation_id")

        if not file_path:
            logger.error("Analysis requested without file_path", payload=payload)
            return

        logger.info("Starting analysis", file=file_path, correlation_id=correlation_id)
        specs = await self.analyzer.analyze(file_path)

        # Publish MEDIA_ANALYZED back to workflow engine
        await self.publisher.publish(
            event_type=EventType.MEDIA_ANALYZED,
            payload={**specs, "correlation_id": correlation_id},
            source_service="analyzer-service",
            correlation_id=correlation_id,
        )
        logger.info("Completed analysis & published event", file=file_path, resolution=specs["resolution"])
