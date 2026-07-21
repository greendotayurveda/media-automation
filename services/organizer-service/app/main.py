"""
Main entrypoint for Media Organizer microservice.
"""
import asyncio
from fastapi import FastAPI
import uvicorn

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.worker import OrganizerWorker

logger = get_logger("organizer-service-main")

app = FastAPI(title="Organizer Service", version=settings.platform_version)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "organizer-service"}


async def main():
    worker = OrganizerWorker()
    worker_task = asyncio.create_task(worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8006, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Organizer Service started")
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
