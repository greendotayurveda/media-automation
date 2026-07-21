"""
Main entrypoint for Workflow Engine microservice.
"""
import asyncio
import signal
from fastapi import FastAPI
import uvicorn

from shared.config.settings import settings
from shared.logging.logger import get_logger
from services.workflow-engine.app.worker import WorkflowWorker

logger = get_logger("workflow-engine-main")

app = FastAPI(
    title="Workflow Engine Service",
    version=settings.platform_version,
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "workflow-engine"}


async def main():
    worker = WorkflowWorker()

    # Graceful shutdown handling
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def shutdown():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass  # Signal handling on Windows

    worker_task = asyncio.create_task(worker.start())

    # Serve lightweight health endpoint in parallel
    config = uvicorn.Config(app=app, host="0.0.0.0", port=8001, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("Workflow Engine service started")
    await stop_event.wait()

    await worker.stop()
    server.should_exit = True
    await asyncio.gather(worker_task, server_task, return_exceptions=True)
    logger.info("Workflow Engine shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
