"""
src/lora.py — LoRA fine-tuning adapter management stub

This module is a STUB — all functions raise NotImplementedError until implemented.

Planned capabilities:
- LoRA fine-tuning job lifecycle (create / status / cancel)
- Adapter versioning and storage
- Hot-swap adapter onto a running Ollama base model
- RLHF / DPO pipeline integration
- Continual fine-tuning scheduler
- Eval-gated promotion (only promote adapter if benchmarks improve)
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class LoRAJob:
    job_id: str
    base_model: str
    dataset_path: str
    adapter_name: str
    status: str  # queued | running | completed | failed | cancelled
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class LoRAAdapter:
    adapter_id: str
    adapter_name: str
    base_model: str
    version: int
    path: str                    # local filesystem path to adapter weights
    benchmark_score: float | None = None
    is_active: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""


# In-memory registries (will be persisted to DB once implemented)
_jobs: dict[str, LoRAJob] = {}
_adapters: dict[str, LoRAAdapter] = {}


# ---------------------------------------------------------------------------
# Fine-tuning job management
# ---------------------------------------------------------------------------

def create_finetune_job(
    base_model: str,
    dataset_path: str,
    adapter_name: str,
    hyperparams: dict | None = None,
) -> LoRAJob:
    """
    Enqueue a LoRA fine-tuning job.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Validate dataset_path (JSONL in Alpaca / ShareGPT format)
    - Allocate GPU via hardware.py
    - Run unsloth / axolotl / LLaMA-Factory in subprocess
    - Write adapter weights to ADAPTER_STORE_DIR
    - Register resulting LoRAAdapter
    """
    raise NotImplementedError(
        "create_finetune_job is not yet implemented. "
        "Planned: unsloth / axolotl fine-tuning job dispatch."
    )


def get_finetune_job(job_id: str) -> LoRAJob | None:
    """Return job by ID, or None. STUB (returns from in-memory dict)."""
    return _jobs.get(job_id)


def list_finetune_jobs(status: str | None = None) -> list[LoRAJob]:
    """List all fine-tuning jobs, optionally filtered by status."""
    jobs = list(_jobs.values())
    if status:
        jobs = [j for j in jobs if j.status == status]
    return jobs


def cancel_finetune_job(job_id: str) -> bool:
    """
    Cancel a queued or running fine-tuning job.

    STUB: raises NotImplementedError for running jobs.
    """
    job = _jobs.get(job_id)
    if not job:
        return False
    if job.status == "queued":
        job.status = "cancelled"
        return True
    raise NotImplementedError(
        "cancel_finetune_job for running jobs is not yet implemented. "
        "Planned: send SIGTERM to subprocess and clean up partial weights."
    )


# ---------------------------------------------------------------------------
# Adapter management
# ---------------------------------------------------------------------------

def list_adapters(base_model: str | None = None) -> list[LoRAAdapter]:
    """List all available LoRA adapters, optionally filtered by base model."""
    adapters = list(_adapters.values())
    if base_model:
        adapters = [a for a in adapters if a.base_model == base_model]
    return adapters


def get_adapter(adapter_id: str) -> LoRAAdapter | None:
    """Return adapter by ID, or None."""
    return _adapters.get(adapter_id)


def apply_adapter(adapter_id: str, base_model: str) -> dict:
    """
    Hot-swap a LoRA adapter onto a running Ollama base model.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Verify adapter weights are on disk
    - Use Ollama Modelfile API to create a merged model
    - Return the new model name
    """
    raise NotImplementedError(
        "apply_adapter is not yet implemented. "
        "Planned: Ollama Modelfile merge with LoRA adapter weights."
    )


def rollback_adapter(adapter_name: str, version: int) -> dict:
    """
    Roll back an adapter to a previous version.

    STUB: raises NotImplementedError.
    """
    raise NotImplementedError(
        "rollback_adapter is not yet implemented. "
        "Planned: swap adapter weights path to previous version checkpoint."
    )


# ---------------------------------------------------------------------------
# Training signal pipeline
# ---------------------------------------------------------------------------

def export_feedback_dataset(
    format: str = "alpaca",
    min_rating: int = 4,
    output_path: str | None = None,
) -> str:
    """
    Export stored feedback signals as a fine-tuning dataset.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Query feedback table for messages with rating >= min_rating
    - Transform to Alpaca / ShareGPT / JSONL format
    - Write to output_path or return inline
    """
    raise NotImplementedError(
        "export_feedback_dataset is not yet implemented. "
        "Planned: query feedback table → format transform → JSONL export."
    )


def generate_synthetic_training_data(
    agent: str = "general",
    n_samples: int = 100,
    topic: str | None = None,
) -> list[dict]:
    """
    Generate synthetic instruction-response pairs for fine-tuning.

    STUB: raises NotImplementedError.
    Implementation plan:
    - Use high-capability provider (Claude / GPT-4o) to generate diverse
      instruction pairs on *topic*
    - Safety-filter each pair
    - Return as Alpaca-format dicts
    """
    raise NotImplementedError(
        "generate_synthetic_training_data is not yet implemented. "
        "Planned: LLM-generated instruction pairs with safety filtering."
    )


# ---------------------------------------------------------------------------
# Production-ready job management API (used by routes.py)
# These functions use SQLite persistence via db.py.
# ---------------------------------------------------------------------------

def create_lora_job(
    base_model: str,
    dataset_path: str,
    adapter_name: str = "adapter",
    config: dict | None = None,
) -> dict:
    """
    Create and persist a new LoRA fine-tuning job with status 'queued'.

    The actual training is not dispatched here — a background worker or
    external orchestrator is expected to pick up queued jobs and advance
    their status via db updates.  This makes the endpoint idempotent and
    testable without GPU hardware.
    """
    from datetime import datetime, timezone
    from src.db import create_finetune_job_record

    if not base_model:
        raise ValueError("base_model is required")
    if not dataset_path:
        raise ValueError("dataset_path is required")

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    return create_finetune_job_record(
        job_id=job_id,
        base_model=base_model,
        dataset_path=dataset_path,
        adapter_name=adapter_name or "adapter",
        config=config or {},
        created_at=now,
    )


def list_lora_jobs(status: str | None = None) -> list[dict]:
    """Return all fine-tuning jobs, optionally filtered by status."""
    from src.db import list_finetune_job_records
    return list_finetune_job_records(status=status)


def get_lora_job(job_id: str) -> dict | None:
    """Return a single fine-tuning job by ID, or None."""
    from src.db import get_finetune_job_record
    return get_finetune_job_record(job_id)


def cancel_lora_job(job_id: str) -> bool:
    """
    Cancel a queued or running fine-tuning job.
    Returns True if the job was cancelled, False if not found or already terminal.
    """
    from src.db import cancel_finetune_job_record
    return cancel_finetune_job_record(job_id)
