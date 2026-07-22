"""
Main entrypoint for Download microservice.
"""
import asyncio

import uvicorn
from fastapi import FastAPI

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.worker import DownloadWorker

logger = get_logger("download-service-main")

app = FastAPI(title="Download Service", version=settings.platform_version)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "download-service"}


async def main():
    worker = DownloadWorker()
    worker_task = asyncio.create_task(worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8008, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Download Service started")
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
