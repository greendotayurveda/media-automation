"""
Main entrypoint for AI microservice.
"""
import asyncio
from typing import Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.ai import AIAssistant
from app.worker import AIWorker

logger = get_logger("ai-service-main")

app = FastAPI(title="AI Service", version=settings.platform_version)
assistant = AIAssistant()


class RecommendRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)
    seed: Optional[str] = None


class AskRequest(BaseModel):
    question: str


class SummarizeRequest(BaseModel):
    overview: Optional[str] = None
    movie_id: Optional[str] = None
    title: Optional[str] = None


@app.get("/health")
async def health_check():
    return await assistant.health()


@app.get("/models")
async def list_models():
    try:
        models = await assistant.list_models()
        return {"models": models, "default": assistant.model}
    except Exception as exc:
        return {"models": [], "default": assistant.model, "error": str(exc)}


@app.post("/recommend")
async def recommend(req: RecommendRequest):
    return await assistant.recommend(limit=req.limit, seed=req.seed)


@app.post("/ask")
async def ask(req: AskRequest):
    return await assistant.ask(req.question)


@app.post("/summarize")
async def summarize(req: SummarizeRequest):
    return await assistant.summarize(
        overview=req.overview,
        movie_id=req.movie_id,
        title=req.title,
    )


async def main():
    worker = AIWorker()
    worker_task = asyncio.create_task(worker.start())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8013, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    logger.info("AI Service started", ollama_url=assistant.base_url)
    await asyncio.gather(worker_task, server_task)


if __name__ == "__main__":
    asyncio.run(main())
