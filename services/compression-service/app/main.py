"""
Main entrypoint for Compression Service microservice.
"""
import asyncio
from fastapi import FastAPI
import uvicorn

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.worker import CompressionWorker

logger = get_logger("compression-service")

app = FastAPI(title="Compression Service", version=settings.platform_version)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "compression-service"}


async def main():
    worker = CompressionWorker()
    asyncio.create_task(worker.start())
    logger.info("Compression Service worker started")

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8005, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
