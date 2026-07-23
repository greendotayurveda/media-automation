"""
Storage Service Redis Streams subscriber + periodic disk checks.
"""
import asyncio
from typing import Any, Dict

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.storage import StorageManager

logger = get_logger("storage-worker")


class StorageWorker(EventSubscriber):
    """
    Periodic disk checks + cleanup on warning/critical.
    Still listens on StreamName.STORAGE for externally published
    STORAGE_WARNING / STORAGE_CRITICAL (does not re-publish there,
    to avoid a self-consume loop).
    """

    stream = StreamName.STORAGE
    consumer_name = "monitor"
    events = [EventType.STORAGE_WARNING, EventType.STORAGE_CRITICAL]

    def __init__(self) -> None:
        super().__init__(service_name="storage-service")
        self.manager = StorageManager()
        self.workflows = EventPublisher(StreamName.WORKFLOWS)
        self._periodic_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._periodic_task = asyncio.create_task(self._periodic_loop())
        try:
            await super().start()
        finally:
            if self._periodic_task:
                self._periodic_task.cancel()

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        correlation_id = payload.get("correlation_id") or raw_event.get("correlation_id")
        # structlog reserves the keyword `event` for the message — never pass event=.
        logger.info(
            "Storage event received — running cleanup",
            event_type=event_type.value,
            correlation_id=correlation_id,
        )
        cleanup = await self.manager.cleanup()
        await self.workflows.publish(
            event_type=EventType.STORAGE_CLEANUP_COMPLETED,
            payload={**cleanup, "trigger": event_type.value, "correlation_id": correlation_id},
            source_service="storage-service",
            correlation_id=correlation_id,
        )

    async def _periodic_loop(self) -> None:
        interval = settings.storage_check_interval_seconds
        logger.info("Storage periodic monitor started", interval_seconds=interval)
        # Initial check shortly after boot
        await asyncio.sleep(5)
        while True:
            try:
                await self.run_check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Periodic storage check failed", error=str(exc))
            await asyncio.sleep(interval)

    async def run_check(self) -> Dict[str, Any]:
        report = await self.manager.collect_report()
        level = report.get("level")

        if level in ("warning", "critical"):
            event_type = (
                EventType.STORAGE_CRITICAL if level == "critical" else EventType.STORAGE_WARNING
            )
            # Publish only to workflows (observability / other consumers).
            # Do not publish back onto stream:storage — this worker consumes that stream.
            await self.workflows.publish(
                event_type=event_type,
                payload=report,
                source_service="storage-service",
            )
            cleanup = await self.manager.cleanup()
            await self.workflows.publish(
                event_type=EventType.STORAGE_CLEANUP_COMPLETED,
                payload={**cleanup, "trigger": f"{level}_auto"},
                source_service="storage-service",
            )
            report["cleanup"] = cleanup

        return report
