"""
Health Service Redis Streams subscriber + daily scan loop.
"""
import asyncio
from typing import Any, Dict

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger
from app.health import HealthScanner

logger = get_logger("health-worker")


class HealthWorker(EventSubscriber):
    """
    Listens on StreamName.HEALTH for HEALTH_SCAN_STARTED and runs periodic scans.
    """

    stream = StreamName.HEALTH
    consumer_name = "scanner"
    events = [EventType.HEALTH_SCAN_STARTED]

    def __init__(self) -> None:
        super().__init__(service_name="health-service")
        self.scanner = HealthScanner()
        self.publisher = EventPublisher(StreamName.HEALTH)
        self.workflows = EventPublisher(StreamName.WORKFLOWS)
        self._periodic_task: asyncio.Task | None = None
        self._scanning = False

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
        scan_type = payload.get("scan_type", "event")
        await self.execute_scan(scan_type=scan_type, correlation_id=correlation_id)

    async def execute_scan(
        self,
        scan_type: str = "scheduled",
        correlation_id: str | None = None,
    ) -> Dict[str, Any]:
        if self._scanning:
            logger.info("Scan already in progress — skipping")
            return {"status": "skipped", "reason": "already_running"}

        self._scanning = True
        try:
            result = await self.scanner.run_scan(scan_type=scan_type)

            for issue in result.get("issues", []):
                await self.publisher.publish(
                    event_type=EventType.HEALTH_ISSUE_FOUND,
                    payload={**issue, "report_id": result["report_id"], "correlation_id": correlation_id},
                    source_service="health-service",
                    correlation_id=correlation_id,
                )

            await self.publisher.publish(
                event_type=EventType.HEALTH_SCAN_COMPLETED,
                payload={**result, "correlation_id": correlation_id},
                source_service="health-service",
                correlation_id=correlation_id,
            )
            await self.workflows.publish(
                event_type=EventType.HEALTH_SCAN_COMPLETED,
                payload={
                    "report_id": result["report_id"],
                    "issues_found": result["issues_found"],
                    "correlation_id": correlation_id,
                },
                source_service="health-service",
                correlation_id=correlation_id,
            )
            return result
        finally:
            self._scanning = False

    async def _periodic_loop(self) -> None:
        interval = settings.health_scan_interval_seconds
        # Loosely honor cron: default daily; health_check_schedule kept for docs/ops
        logger.info(
            "Health periodic scanner started",
            interval_seconds=interval,
            schedule=settings.health_check_schedule,
        )
        await asyncio.sleep(10)
        while True:
            try:
                await self.publisher.publish(
                    event_type=EventType.HEALTH_SCAN_STARTED,
                    payload={"scan_type": "scheduled"},
                    source_service="health-service",
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Failed to publish scheduled health scan", error=str(exc))
            await asyncio.sleep(interval)
