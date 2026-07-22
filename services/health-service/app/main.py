"""
Main entrypoint for Health microservice.
"""
import asyncio

import uvicorn
from fastapi import FastAPI

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.logging.logger import get_logger
from app.health import HealthScanner
from app.worker import HealthWorker

logger = get_logger("health-service-main")

app = FastAPI(title="Health Service", version=settings.platform_version)
scanner = HealthScanner()
health_bus = EventPublisher(StreamName.HEALTH)
_worker: HealthWorker | None = None


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "health-service"}


@app.post("/scan")
async def trigger_scan():
    """Kick off a manual health scan (runs immediately when worker is local)."""
    if _worker:
        result = await _worker.execute_scan(scan_type="manual")
        return {"status": "ok", **result}
    await health_bus.publish(
        event_type=EventType.HEALTH_SCAN_STARTED,
        payload={"scan_type": "manual"},
        source_service="health-service",
    )
    return {"status": "queued"}


@app.get("/reports")
async def list_reports():
    reports = await scanner.list_reports()
    open_issues = await scanner.open_issue_count()
    return {"reports": reports, "open_issues": open_issues}


async def main():
    global _worker
    _worker = HealthWorker()
    worker_task = asyncio.create_task(_worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8011, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Health Service started")
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
