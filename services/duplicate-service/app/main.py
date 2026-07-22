"""
Main entrypoint for Duplicate detection microservice.
"""
import asyncio

import uvicorn
from fastapi import FastAPI

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.duplicates import DuplicateDetector
from app.worker import DuplicateWorker

logger = get_logger("duplicate-service-main")

app = FastAPI(title="Duplicate Service", version=settings.platform_version)
detector = DuplicateDetector()


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "duplicate-service"}


@app.post("/scan")
async def scan_library():
    """Trigger a full library duplicate scan."""
    result = await detector.scan_library()
    return {
        "status": "ok",
        "detected_count": len(result.get("detected", [])),
        "resolved_count": len(result.get("resolved", [])),
        **result,
    }


@app.post("/resolve/{duplicate_id}")
async def resolve_duplicate(duplicate_id: str):
    resolved = await detector.resolve_duplicate(duplicate_id)
    if not resolved:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Duplicate not found")
    return resolved


async def main():
    worker = DuplicateWorker()
    worker_task = asyncio.create_task(worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8009, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Duplicate Service started")
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
