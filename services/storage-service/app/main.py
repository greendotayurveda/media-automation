"""
Main entrypoint for Storage microservice.
"""
import asyncio

import uvicorn
from fastapi import FastAPI

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.logging.logger import get_logger
from app.storage import StorageManager
from app.worker import StorageWorker

logger = get_logger("storage-service-main")

app = FastAPI(title="Storage Service", version=settings.platform_version)
manager = StorageManager()
workflows = EventPublisher(StreamName.WORKFLOWS)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "storage-service"}


@app.get("/report")
async def get_report():
    """Return latest persisted report, or collect a fresh one."""
    latest = await manager.latest_report()
    if latest:
        return latest
    return await manager.collect_report()


@app.post("/cleanup")
async def trigger_cleanup():
    """Run cleanup immediately and publish STORAGE_CLEANUP_COMPLETED."""
    cleanup = await manager.cleanup()
    report = await manager.collect_report()
    await workflows.publish(
        event_type=EventType.STORAGE_CLEANUP_COMPLETED,
        payload={**cleanup, "trigger": "api", "report": report},
        source_service="storage-service",
    )
    return {"status": "ok", "cleanup": cleanup, "report": report}


async def main():
    worker = StorageWorker()
    worker_task = asyncio.create_task(worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8010, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Storage Service started")
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
