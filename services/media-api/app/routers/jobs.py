"""
FastAPI router for Workflow Jobs monitoring (/api/v1/jobs).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.connection import get_db
from shared.database.models.workflow import WorkflowJob

router = APIRouter(prefix="/api/v1/jobs", tags=["Workflow Jobs"])


class JobResponse(BaseModel):
    id: str
    name: str
    correlation_id: str
    status: str
    payload: Dict[str, Any]

    class Config:
        from_attributes = True


@router.get("", response_model=List[JobResponse])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """List recent workflow orchestrator jobs."""
    result = await db.execute(select(WorkflowJob).order_by(WorkflowJob.created_at.desc()).limit(50))
    return result.scalars().all()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get details of a specific workflow job."""
    result = await db.execute(select(WorkflowJob).where(WorkflowJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
