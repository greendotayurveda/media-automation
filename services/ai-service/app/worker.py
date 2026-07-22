"""
Optional AI worker: cache summaries when media becomes ready / identified.
"""
from typing import Any, Dict

from shared.events.events import EventType, StreamName
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.ai import AIAssistant

logger = get_logger("ai-worker")


class AIWorker(EventSubscriber):
    """
    Lightweight listener on WORKFLOWS for MEDIA_READY / METADATA_IDENTIFIED.
    """

    stream = StreamName.WORKFLOWS
    consumer_name = "summarizer"
    events = [EventType.MEDIA_READY, EventType.METADATA_IDENTIFIED]

    def __init__(self) -> None:
        super().__init__(service_name="ai-service")
        self.ai = AIAssistant()

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        movie_id = payload.get("movie_id")
        overview = payload.get("overview")
        title = payload.get("title")
        if not movie_id and not overview:
            return

        logger.info(
            "Generating summary cache",
            event=event_type.value,
            movie_id=movie_id,
            title=title,
        )
        result = await self.ai.summarize(
            movie_id=movie_id,
            overview=overview,
            title=title,
        )
        logger.info(
            "Summary cached",
            movie_id=movie_id,
            summary_len=len(result.get("summary") or ""),
        )
