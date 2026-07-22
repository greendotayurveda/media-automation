"""
Dashboard static UI served via FastAPI StaticFiles.
"""
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from shared.config.settings import settings
from shared.logging.logger import get_logger

logger = get_logger("dashboard")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Media Platform Dashboard", version=settings.platform_version)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "dashboard"}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    logger.info("Dashboard starting on :8014")
    uvicorn.run(app, host="0.0.0.0", port=8014, log_level="warning")
