"""
Main FastAPI entrypoint for central Media API microservice.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config.settings import settings
from shared.logging.logger import get_logger
from services.media-api.app.routers import downloads, health, jobs, movies, storage

logger = get_logger("media-api")

app = FastAPI(
    title="Media Automation Platform API",
    description="Central gateway API for Media Automation Platform",
    version=settings.platform_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware configuration
origins = [origin.strip() for origin in settings.api_cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(movies.router)
app.include_router(downloads.router)
app.include_router(jobs.router)
app.include_router(health.router)
app.include_router(storage.router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "platform": settings.platform_name,
        "version": settings.platform_version,
        "docs": "/docs",
    }


@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "ok", "service": "media-api"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.api_host, port=settings.api_port, reload=True)
