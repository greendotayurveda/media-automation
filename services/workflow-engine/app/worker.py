"""
Workflow Engine Redis Streams subscriber worker.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.engine import WorkflowOrchestrator

logger = get_logger("workflow-engine-worker")


class WorkflowWorker(EventSubscriber):
    """
    Subscriber listening to stream events across all pipeline domains.
    """

    # We listen to stream:workflows and stream:media by default
    stream = StreamName.WORKFLOWS
    consumer_name = "orchestrator"

    events = [
        EventType.DOWNLOAD_COMPLETED,
        EventType.MOVIE_RECEIVED,
        EventType.MEDIA_ANALYZED,
        EventType.METADATA_IDENTIFIED,
        EventType.SUBTITLE_DOWNLOADED,
        EventType.SUBTITLE_NOT_FOUND,
        EventType.QUALITY_CHECKED,
        EventType.FILE_ORGANIZED,
        EventType.JELLYFIN_REFRESHED,
        EventType.MEDIA_ANALYZE_FAILED,
        EventType.METADATA_IDENTIFY_FAILED,
        EventType.DOWNLOAD_FAILED,
    ]

    def __init__(self) -> None:
        super().__init__(service_name="workflow-engine")
        self.orchestrator = WorkflowOrchestrator()

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        """Pass incoming events into the orchestrator."""
        logger.info(
            "Workflow worker handling event",
            event_type=event_type.value,
            correlation_id=payload.get("correlation_id") or raw_event.get("correlation_id"),
        )
        await self.orchestrator.handle_event(event_type, payload, raw_event)
