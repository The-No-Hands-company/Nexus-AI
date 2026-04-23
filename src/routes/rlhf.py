"""
src/routes/rlhf.py — API routes for RLHF and DPO training

Endpoints:
  POST   /v1/rlhf/dpo/prepare       - Prepare DPO dataset
  POST   /v1/rlhf/dpo/job           - Create DPO job
  GET    /v1/rlhf/dpo/job/{job_id}  - Get DPO job status
  GET    /v1/rlhf/dpo/jobs          - List DPO jobs
  POST   /v1/rlhf/job               - Create RLHF job
  GET    /v1/rlhf/job/{job_id}      - Get RLHF job status
  GET    /v1/rlhf/jobs              - List RLHF jobs
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, BackgroundTasks
from pydantic import BaseModel, Field

from src.rlhf_dpo import (
    prepare_dpo_dataset,
    create_dpo_job,
    run_dpo_training,
    get_dpo_job,
    list_dpo_jobs,
    create_rlhf_job,
    run_rlhf_training,
    get_rlhf_job,
    list_rlhf_jobs,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/rlhf", tags=["RLHF/DPO"])


# ───────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ───────────────────────────────────────────────────────────────────────────


class DPODatasetPrepareRequest(BaseModel):
    """Request to prepare a DPO dataset."""
    min_margin: float = Field(default=0.6, ge=0.0, le=1.0, description="Minimum confidence margin")
    dedup_window: int = Field(default=7, ge=1, description="Deduplication lookback window (days)")
    max_length: int = Field(default=2048, ge=256, description="Max tokens per response")


class DPOJobCreateRequest(BaseModel):
    """Request to create a DPO training job."""
    base_model: str = Field(..., description="HuggingFace model ID")
    dataset_path: str = Field(..., description="Path to prepared DPO dataset")
    adapter_name: str = Field(default="dpo_adapter", description="Name for adapter")
    config: Optional[dict] = Field(default=None, description="Hyperparameter overrides")


class DPOJobResponse(BaseModel):
    """Response containing DPO job details."""
    job_id: str
    base_model: str
    adapter_name: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    metrics: dict
    adapter_path: Optional[str] = None


class RLHFJobCreateRequest(BaseModel):
    """Request to create an RLHF training job."""
    base_model: str = Field(..., description="HuggingFace model ID")
    dataset_path: str = Field(..., description="Path to base dataset")
    adapter_name: str = Field(default="rlhf_adapter", description="Name for adapter")
    config: Optional[dict] = Field(default=None, description="Hyperparameter overrides")


class RLHFJobResponse(BaseModel):
    """Response containing RLHF job details."""
    job_id: str
    base_model: str
    adapter_name: str
    status: str
    rounds_completed: int
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    metrics: dict
    adapter_path: Optional[str] = None
    reward_model_path: Optional[str] = None


# ───────────────────────────────────────────────────────────────────────────
# DPO Endpoints
# ───────────────────────────────────────────────────────────────────────────


@router.post("/dpo/prepare", response_model=dict, summary="Prepare DPO dataset")
async def prepare_dpo(
    file: UploadFile = File(..., description="JSONL file with preference pairs"),
    request: DPODatasetPrepareRequest = DPODatasetPrepareRequest(),
) -> dict:
    """
    Prepare a DPO dataset from uploaded preference pairs.

    Input JSONL format:
    ```json
    {"prompt": "...", "chosen": "...", "rejected": "...", "margin": 1.0}
    ```

    Validates, filters by margin, deduplicates, and returns path to output dataset.

    Returns:
      - `output_path`: Path to prepared dataset
      - `num_pairs`: Number of valid pairs after filtering
    """
    try:
        # Save upload to temporary file
        import tempfile
        fd, temp_input = tempfile.mkstemp(suffix=".jsonl")
        try:
            content = await file.read()
            os.write(fd, content)
            os.close(fd)

            # Prepare dataset
            output_path = prepare_dpo_dataset(
                input_path=temp_input,
                min_margin=request.min_margin,
                dedup_window=request.dedup_window,
                max_length=request.max_length,
            )

            # Count pairs
            import json as _json
            num_pairs = 0
            with open(output_path) as f:
                for line in f:
                    if line.strip():
                        num_pairs += 1

            return {
                "output_path": output_path,
                "num_pairs": num_pairs,
                "status": "success",
            }
        finally:
            if os.path.exists(temp_input):
                os.remove(temp_input)

    except Exception as exc:
        logger.exception("DPO dataset preparation failed")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/dpo/job", response_model=DPOJobResponse, summary="Create DPO job")
async def create_dpo_training_job(
    request: DPOJobCreateRequest,
    background_tasks: BackgroundTasks,
) -> DPOJobResponse:
    """
    Create and enqueue a DPO fine-tuning job.

    The job will be picked up by a background worker. Returns immediately
    with status="queued".

    Args:
        request: Job configuration

    Returns:
        DPOJobResponse with job_id and status
    """
    try:
        job = create_dpo_job(
            base_model=request.base_model,
            dataset_path=request.dataset_path,
            adapter_name=request.adapter_name,
            config=request.config,
        )

        # Optionally run training in background
        # background_tasks.add_task(run_dpo_training, job)

        return DPOJobResponse(
            job_id=job.job_id,
            base_model=job.base_model,
            adapter_name=job.adapter_name,
            status=job.status,
            created_at=job.created_at,
            metrics=job.metrics,
        )

    except Exception as exc:
        logger.exception("DPO job creation failed")
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/dpo/job/{job_id}", response_model=DPOJobResponse, summary="Get DPO job")
async def get_dpo_job_endpoint(job_id: str) -> DPOJobResponse:
    """
    Get status and details of a DPO job.

    Args:
        job_id: Job ID

    Returns:
        DPOJobResponse with current status and metrics
    """
    job = get_dpo_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="DPO job not found")

    return DPOJobResponse(
        job_id=job.job_id,
        base_model=job.base_model,
        adapter_name=job.adapter_name,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error=job.error,
        metrics=job.metrics,
        adapter_path=job.adapter_path,
    )


@router.get("/dpo/jobs", response_model=list[DPOJobResponse], summary="List DPO jobs")
async def list_dpo_jobs_endpoint(
    status: Optional[str] = Query(None, description="Filter by status"),
) -> list[DPOJobResponse]:
    """
    List all DPO jobs, optionally filtered by status.

    Query parameters:
      - `status`: Filter by status (queued, running, completed, failed)

    Returns:
        List of DPOJobResponse objects
    """
    jobs = list_dpo_jobs(status=status)
    return [
        DPOJobResponse(
            job_id=j.job_id,
            base_model=j.base_model,
            adapter_name=j.adapter_name,
            status=j.status,
            created_at=j.created_at,
            completed_at=j.completed_at,
            error=j.error,
            metrics=j.metrics,
            adapter_path=j.adapter_path,
        )
        for j in jobs
    ]


# ───────────────────────────────────────────────────────────────────────────
# RLHF Endpoints
# ───────────────────────────────────────────────────────────────────────────


@router.post("/job", response_model=RLHFJobResponse, summary="Create RLHF job")
async def create_rlhf_training_job(
    request: RLHFJobCreateRequest,
    background_tasks: BackgroundTasks,
) -> RLHFJobResponse:
    """
    Create and enqueue an RLHF (reward model + supervised FT) job.

    The job will be picked up by a background worker. Returns immediately
    with status="queued".

    Args:
        request: Job configuration

    Returns:
        RLHFJobResponse with job_id and status
    """
    try:
        job = create_rlhf_job(
            base_model=request.base_model,
            dataset_path=request.dataset_path,
            adapter_name=request.adapter_name,
            config=request.config,
        )

        # Optionally run training in background
        # background_tasks.add_task(run_rlhf_training, job)

        return RLHFJobResponse(
            job_id=job.job_id,
            base_model=job.base_model,
            adapter_name=job.adapter_name,
            status=job.status,
            rounds_completed=job.rounds_completed,
            created_at=job.created_at,
            metrics=job.metrics,
        )

    except Exception as exc:
        logger.exception("RLHF job creation failed")
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/job/{job_id}", response_model=RLHFJobResponse, summary="Get RLHF job")
async def get_rlhf_job_endpoint(job_id: str) -> RLHFJobResponse:
    """
    Get status and details of an RLHF job.

    Args:
        job_id: Job ID

    Returns:
        RLHFJobResponse with current status, rounds, and metrics
    """
    job = get_rlhf_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="RLHF job not found")

    return RLHFJobResponse(
        job_id=job.job_id,
        base_model=job.base_model,
        adapter_name=job.adapter_name,
        status=job.status,
        rounds_completed=job.rounds_completed,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error=job.error,
        metrics=job.metrics,
        adapter_path=job.adapter_path,
        reward_model_path=job.reward_model_path,
    )


@router.get("/jobs", response_model=list[RLHFJobResponse], summary="List RLHF jobs")
async def list_rlhf_jobs_endpoint(
    status: Optional[str] = Query(None, description="Filter by status"),
) -> list[RLHFJobResponse]:
    """
    List all RLHF jobs, optionally filtered by status.

    Query parameters:
      - `status`: Filter by status (queued, running, completed, failed)

    Returns:
        List of RLHFJobResponse objects
    """
    jobs = list_rlhf_jobs(status=status)
    return [
        RLHFJobResponse(
            job_id=j.job_id,
            base_model=j.base_model,
            adapter_name=j.adapter_name,
            status=j.status,
            rounds_completed=j.rounds_completed,
            created_at=j.created_at,
            completed_at=j.completed_at,
            error=j.error,
            metrics=j.metrics,
            adapter_path=j.adapter_path,
            reward_model_path=j.reward_model_path,
        )
        for j in jobs
    ]


# ───────────────────────────────────────────────────────────────────────────
# Health/Status
# ───────────────────────────────────────────────────────────────────────────


@router.get("/health", summary="RLHF system health")
async def health_check() -> dict:
    """
    Check RLHF/DPO system health and job queue status.

    Returns:
        - `status`: "healthy" or "degraded"
        - `dpo_jobs_queued`: Number of queued DPO jobs
        - `rlhf_jobs_queued`: Number of queued RLHF jobs
    """
    dpo_queued = len(list_dpo_jobs(status="queued"))
    rlhf_queued = len(list_rlhf_jobs(status="queued"))

    status = "healthy" if dpo_queued + rlhf_queued < 100 else "degraded"

    return {
        "status": status,
        "dpo_jobs_queued": dpo_queued,
        "rlhf_jobs_queued": rlhf_queued,
    }
