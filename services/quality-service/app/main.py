"""
Main entrypoint for Quality microservice.
"""
import asyncio

import uvicorn
from fastapi import FastAPI

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.worker import QualityWorker

logger = get_logger("quality-service-main")

app = FastAPI(title="Quality Service", version=settings.platform_version)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "quality-service"}


async def main():
    worker = QualityWorker()
    worker_task = asyncio.create_task(worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8007, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Quality Service started")
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
