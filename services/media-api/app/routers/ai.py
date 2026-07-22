"""
Gateway proxy routes for AI service (/api/v1/ai).
"""
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ai", tags=["AI"])
AI_BASE = "http://ai-service:8013"


class RecommendRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)
    seed: Optional[str] = None


class AskRequest(BaseModel):
    question: str


class SummarizeRequest(BaseModel):
    overview: Optional[str] = None
    movie_id: Optional[str] = None
    title: Optional[str] = None


async def _proxy(method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.request(method, f"{AI_BASE}{path}", json=json_body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ai-service unavailable: {exc}") from exc


@router.get("/health")
async def ai_health():
    return await _proxy("GET", "/health")


@router.get("/models")
async def ai_models():
    return await _proxy("GET", "/models")


@router.post("/recommend")
async def ai_recommend(req: RecommendRequest):
    return await _proxy("POST", "/recommend", req.model_dump())


@router.post("/ask")
async def ai_ask(req: AskRequest):
    return await _proxy("POST", "/ask", req.model_dump())


@router.post("/summarize")
async def ai_summarize(req: SummarizeRequest):
    return await _proxy("POST", "/summarize", req.model_dump())
