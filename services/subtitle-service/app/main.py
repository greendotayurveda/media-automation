"""
Main entrypoint for Subtitle microservice.
"""
import asyncio
from fastapi import FastAPI
import uvicorn

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.worker import SubtitleWorker

logger = get_logger("subtitle-service-main")

app = FastAPI(title="Subtitle Service", version=settings.platform_version)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "subtitle-service"}


async def main():
    worker = SubtitleWorker()
    worker_task = asyncio.create_task(worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8005, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Subtitle Service started")
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
