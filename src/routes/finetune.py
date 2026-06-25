"""Fine-tuning routes.

Extracted from src/api/routes.py for maintainability.
Covers: v1 fine-tuning, finetune jobs/adapters/datasets/curation,
synthetic data, multimodal, distillation, nexus-prime-alpha wiring,
RLHF/DPO experiments, and continual finetuning.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ._helpers import (
    _api_error,
    _read_json_body,
    _v1_error,
)
from ..db import (
    init_db,
    create_fine_tuning_job as db_create_fine_tuning_job,
    get_fine_tuning_job as db_get_fine_tuning_job,
    list_fine_tuning_jobs as db_list_fine_tuning_jobs,
    update_fine_tuning_job as db_update_fine_tuning_job,
    create_fine_tuning_job_event as db_create_fine_tuning_job_event,
    list_fine_tuning_job_events as db_list_fine_tuning_job_events,
    load_pref as db_load_pref,
    save_pref as db_save_pref,
    save_ft_training_sample as db_save_ft_training_sample,
    list_ft_training_samples as db_list_ft_training_samples,
)
from ..scheduler import (
    schedule_job,
    list_jobs,
    cancel_job,
    job_to_dict,
)
from ..agent import (
    call_llm_with_fallback,
    update_config,
    set_provider_persona_override,
)
from ..personas import set_persona

router = APIRouter(prefix="", tags=["finetune"])

@router.get("/v1/fine-tuning/training-samples")
def v1_list_training_samples(limit: int = 100, min_quality: float = 0.0):
    safe_limit = min(max(int(limit or 100), 1), 500)
    safe_quality = max(0.0, min(float(min_quality or 0.0), 1.0))
    return {
        "object": "list",
        "data": db_list_ft_training_samples(limit=safe_limit, min_quality=safe_quality),
    }


@router.post("/v1/fine-tuning/training-samples/export")
async def v1_export_training_samples(request: Request):
    from .v1 import _ensure_files_dir, _file_meta_path, _FILES_DIR

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    min_quality = max(0.0, min(float(body.get("min_quality", 0.7) or 0.7), 1.0))
    limit = min(max(int(body.get("limit", 200) or 200), 1), 1000)
    model = str(body.get("model", "gpt-3.5-turbo") or "gpt-3.5-turbo")

    samples = db_list_ft_training_samples(limit=limit, min_quality=min_quality)
    if not samples:
        return _v1_error("no training samples matched the requested filter", "not_found_error", 404)

    _ensure_files_dir()
    file_id = f"file-{uuid.uuid4().hex[:12]}"
    data_path = os.path.join(_FILES_DIR, file_id)
    lines = []
    for sample in samples:
        lesson_text = "\n".join(f"- {lesson}" for lesson in (sample.get("lessons") or []))
        messages = [
            {"role": "system", "content": "You are a helpful assistant that improves future responses using retrospective quality signals."},
            {"role": "user", "content": str(sample.get("task") or "")},
            {"role": "assistant", "content": str(sample.get("result") or "")},
        ]
        completion = str(sample.get("result") or "")
        if lesson_text:
            completion += "\n\nRetrospective lessons:\n" + lesson_text
        lines.append(json.dumps({"messages": messages, "completion": completion}))

    with open(data_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    meta = {
        "id": file_id,
        "object": "file",
        "bytes": os.path.getsize(data_path),
        "created_at": int(time.time()),
        "filename": f"reflection-training-{model.replace('/', '-')}.jsonl",
        "purpose": "fine-tune",
        "status": "processed",
        "sample_count": len(samples),
        "min_quality": min_quality,
    }
    with open(_file_meta_path(file_id), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)

    return meta


# ─────────────────────────────────────────────────────────────────────────────
# Fine-tuning API  — persisted compatibility lifecycle (/v1/fine-tuning/jobs)
# ─────────────────────────────────────────────────────────────────────────────

def _run_fine_tuning_job(job_id: str):
    """Background lifecycle for compatibility fine-tuning jobs.

    This keeps OpenAI-compatible job states realistic while the backend
    remains a compatibility implementation rather than a real trainer.
    """
    from .v1 import _load_file_meta

    try:
        job = db_get_fine_tuning_job(job_id)
        if not job or job.get("status") != "queued":
            return

        db_update_fine_tuning_job(job_id, status="running")
        db_create_fine_tuning_job_event(job_id, "Job status changed to running", data={"status": "running"})
        time.sleep(0.6)

        job = db_get_fine_tuning_job(job_id)
        if not job or job.get("status") == "cancelled":
            return

        training_meta = _load_file_meta(str(job.get("training_file") or "")) or {}
        trained_tokens = max(128, int(training_meta.get("bytes", 0) // 4))
        ft_model = f"ft:{job.get('model', 'model')}:{job_id[-6:]}"
        db_update_fine_tuning_job(
            job_id,
            status="succeeded",
            fine_tuned_model=ft_model,
            trained_tokens=trained_tokens,
            finished_at=int(time.time()),
            result_files=[str(job.get("training_file") or "")],
        )
        db_create_fine_tuning_job_event(
            job_id,
            "Job completed successfully",
            data={"status": "succeeded", "fine_tuned_model": ft_model, "trained_tokens": trained_tokens},
        )
        try:
            from ..eval_pipeline import run_regression_benchmark

            suites = ["gsm8k", "arc", "safety"]
            hyperparams = job.get("hyperparameters") if isinstance(job.get("hyperparameters"), dict) else {}
            regression_provider = str(hyperparams.get("regression_provider") or "offline").strip() or "offline"
            regression = run_regression_benchmark(
                model=str(job.get("model") or "nexus-prime-base"),
                provider=regression_provider,
                suites=suites,
                threshold=0.05,
                n_samples=8,
            )
            db_create_fine_tuning_job_event(
                job_id,
                "Post-train regression benchmark completed",
                data={
                    "suites": suites,
                    "provider": regression_provider,
                    "overall_regression": bool(regression.get("overall_regression")),
                    "current_avg": regression.get("current_avg"),
                },
            )
        except Exception as exc:
            db_create_fine_tuning_job_event(
                job_id,
                "Post-train regression benchmark skipped",
                level="warning",
                data={"error": str(exc)[:300]},
            )
    except Exception as exc:
        db_update_fine_tuning_job(
            job_id,
            status="failed",
            finished_at=int(time.time()),
            error={"message": str(exc), "code": "fine_tuning_job_error"},
        )
        db_create_fine_tuning_job_event(
            job_id,
            "Job failed",
            level="error",
            data={"status": "failed", "error": str(exc)},
        )


@router.post("/v1/fine-tuning/jobs")
async def v1_create_fine_tuning_job(request: Request):
    from .v1 import _load_file_meta
    from ..api.schemas import FineTuningRequest, FineTuningJob

    try:
        body = await request.json()
        payload = FineTuningRequest(**body)
    except Exception as exc:
        return _v1_error(str(exc), "validation_error", 422)

    if not _load_file_meta(payload.training_file):
        return _v1_error(
            f"training_file '{payload.training_file}' not found. Upload it via POST /v1/files first.",
            "invalid_request_error", 400,
        )

    init_db()
    job = FineTuningJob(
        model=payload.model,
        training_file=payload.training_file,
        validation_file=payload.validation_file,
        hyperparameters=payload.hyperparameters or {},
        status="queued",
    ).model_dump()
    db_create_fine_tuning_job(job)
    db_create_fine_tuning_job_event(job["id"], "Job created", data={"status": "queued"})

    threading.Thread(target=_run_fine_tuning_job, args=(job["id"],), daemon=True).start()
    return job


@router.get("/v1/fine-tuning/jobs")
def v1_list_fine_tuning_jobs(limit: int = 20, after: str = ""):
    init_db()
    safe_limit = min(max(int(limit or 20), 1), 100)
    items = db_list_fine_tuning_jobs(limit=safe_limit + 1, after=after)
    return {
        "object": "list",
        "data": items[:safe_limit],
        "has_more": len(items) > safe_limit,
    }


@router.get("/v1/fine-tuning/jobs/{job_id}")
def v1_get_fine_tuning_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)
    return job


@router.post("/v1/fine-tuning/jobs/{job_id}/cancel")
def v1_cancel_fine_tuning_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)

    if job.get("status") in {"succeeded", "failed", "cancelled"}:
        return job

    db_update_fine_tuning_job(
        job_id,
        status="cancelled",
        finished_at=int(time.time()),
        error={"message": "Cancelled by user", "code": "cancelled"},
    )
    db_create_fine_tuning_job_event(job_id, "Job cancelled", data={"status": "cancelled"})
    return db_get_fine_tuning_job(job_id)


@router.get("/v1/fine-tuning/jobs/{job_id}/events")
def v1_list_fine_tuning_job_events(job_id: str, limit: int = 100):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        return _v1_error("fine-tuning job not found", "not_found_error", 404)

    events = db_list_fine_tuning_job_events(job_id, limit=limit)
    return {
        "object": "list",
        "data": [
            {
                "id": event.get("id"),
                "object": "fine_tuning.job.event",
                "created_at": int(event.get("created_at") or 0),
                "level": event.get("level", "info"),
                "message": event.get("message", ""),
                "data": event.get("data", {}),
            }
            for event in events
        ],
        "has_more": False,
    }
# ─────────────────────────────────────────────────────────────────────────────
# Section 12 compatibility aliases (/finetune/jobs)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/finetune/jobs")
async def create_finetune_job(request: Request):
    """Create a persisted fine-tuning job with queued status."""
    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    training_file = str(body.get("training_file") or "").strip()
    validation_file = str(body.get("validation_file") or "").strip() or None
    hyperparameters = body.get("hyperparameters") if isinstance(body.get("hyperparameters"), dict) else {}

    from ..api.schemas import FineTuningJob

    init_db()
    job = FineTuningJob(
        model=model,
        training_file=training_file,
        validation_file=validation_file,
        hyperparameters=hyperparameters,
        status="queued",
    ).model_dump()
    db_create_fine_tuning_job(job)
    db_create_fine_tuning_job_event(job["id"], "Job created", data={"status": "queued"})
    threading.Thread(target=_run_fine_tuning_job, args=(job["id"],), daemon=True).start()
    return {
        "id": job["id"],
        "status": job["status"],
        "model": job["model"],
        "training_file": job.get("training_file"),
        "validation_file": job.get("validation_file"),
        "created_at": job.get("created_at"),
        "object": "finetune.job",
    }


@router.get("/finetune/jobs")
def list_finetune_jobs(limit: int = 100, status: str = ""):
    init_db()
    safe_limit = max(1, min(int(limit), 500))
    rows = db_list_fine_tuning_jobs(limit=safe_limit)
    status_filter = (status or "").strip().lower()
    if status_filter:
        rows = [r for r in rows if str(r.get("status", "")).lower() == status_filter]
    return {
        "count": len(rows),
        "items": rows,
    }


@router.get("/finetune/jobs/{job_id}")
def get_finetune_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="finetune job not found")
    return job


@router.delete("/finetune/jobs/{job_id}")
def cancel_finetune_job(job_id: str):
    init_db()
    job = db_get_fine_tuning_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="finetune job not found")

    if job.get("status") in {"queued", "running"}:
        db_update_fine_tuning_job(
            job_id,
            status="cancelled",
            finished_at=int(time.time()),
            error={"message": "Cancelled by user", "code": "cancelled"},
        )
        db_create_fine_tuning_job_event(job_id, "Job cancelled", data={"status": "cancelled"})

    return db_get_fine_tuning_job(job_id)


def _training_rows_from_feedback(include_trace: bool = True, limit: int = 5000) -> list[dict]:
    from ..db import load_feedback_export
    from .agent import _load_feedback_trace_events

    feedback_rows = load_feedback_export(limit=limit)
    trace_rows = _load_feedback_trace_events(limit=limit) if include_trace else []

    rows: list[dict] = []
    if trace_rows:
        for item in trace_rows:
            rows.append(
                {
                    "prompt": str(item.get("prompt") or ""),
                    "response": str(item.get("response") or ""),
                    "provider": str(item.get("provider") or ""),
                    "model": str(item.get("model") or ""),
                    "persona": str(item.get("persona") or ""),
                    "chat_id": str(item.get("chat_id") or ""),
                    "message_idx": int(item.get("message_idx") or 0),
                    "created_at": str(item.get("created_at") or ""),
                    "source": "trace",
                }
            )
    else:
        for item in feedback_rows:
            rows.append(
                {
                    "prompt": "",
                    "response": str(item.get("reaction") or ""),
                    "provider": str(item.get("provider") or ""),
                    "model": str(item.get("model") or ""),
                    "persona": "",
                    "chat_id": str(item.get("chat_id") or ""),
                    "message_idx": int(item.get("message_idx") or 0),
                    "created_at": str(item.get("ts") or ""),
                    "source": "reaction",
                }
            )
    return rows


def _dataset_checksum(rows: list[dict]) -> str:
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _create_finetune_job_from_rows(
    model: str,
    rows: list[dict],
    source: str,
    provenance_extra: dict | None = None,
    dataset_format: str = "jsonl",
    auto_start: bool = True,
) -> dict:
    from ..api.schemas import FineTuningJob
    from ..db import save_ft_dataset_version

    checksum = _dataset_checksum(rows)
    dataset_id = f"dsver-{uuid.uuid4().hex[:10]}"
    provenance = {
        "source": source,
        "row_count": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if isinstance(provenance_extra, dict):
        provenance.update(provenance_extra)

    dataset_version = save_ft_dataset_version(
        dataset_id=dataset_id,
        source=source,
        fmt=dataset_format,
        row_count=len(rows),
        provenance=provenance,
        checksum=checksum,
        preview_rows=rows,
    )

    training_file = f"inline://dataset/{dataset_id}"
    job = FineTuningJob(
        model=model,
        training_file=training_file,
        validation_file=None,
        hyperparameters={
            "dataset_version_id": dataset_id,
            "dataset_checksum": checksum,
            "provenance": provenance,
        },
        status="queued",
    ).model_dump()
    db_create_fine_tuning_job(job)
    db_create_fine_tuning_job_event(
        job["id"],
        "Fine-tune created",
        data={"status": "queued", "dataset_version_id": dataset_id, "source": source},
    )
    if auto_start:
        threading.Thread(target=_run_fine_tuning_job, args=(job["id"],), daemon=True).start()

    return {
        "job": {
            "id": job["id"],
            "status": job["status"],
            "model": job["model"],
            "training_file": training_file,
            "object": "finetune.job",
        },
        "dataset_version": dataset_version,
    }

@router.get("/finetune/adapters/active")
def get_active_finetune_adapter():
    from ..db import get_active_lora_adapter

    return {"active_adapter": get_active_lora_adapter()}


def _run_model_update_regression_gate(
    model: str,
    provider: str,
    suites: list[str] | None,
    threshold: float,
    n_samples: int,
    enforce: bool,
) -> dict:
    """Run regression benchmark for model-update actions and return gate metadata."""
    from ..eval_pipeline import run_regression_benchmark

    selected_suites = [str(s).strip() for s in (suites or ["gsm8k", "arc", "safety"]) if str(s).strip()]
    result = run_regression_benchmark(
        model=model,
        provider=provider,
        suites=selected_suites,
        threshold=float(threshold),
        n_samples=max(1, int(n_samples)),
    )
    rows = result.get("suite_results") if isinstance(result.get("suite_results"), list) else []
    avg_score = 0.0
    if rows:
        avg_score = sum(float(r.get("score") or 0.0) for r in rows) / max(1, len(rows))
    has_regression = not bool(result.get("ok", True))
    return {
        "enforced": bool(enforce),
        "allowed": (not has_regression) or (not bool(enforce)),
        "regression_count": int(result.get("regression_count") or 0),
        "has_regression": has_regression,
        "threshold": float(threshold),
        "provider": provider,
        "suites": selected_suites,
        "n_samples": max(1, int(n_samples)),
        "average_score": round(avg_score, 4),
        "benchmark": result,
    }


@router.get("/finetune/adapters")
def list_finetune_adapters(adapter_id: str = ""):
    from ..db import list_lora_adapter_versions

    rows = list_lora_adapter_versions(adapter_id=adapter_id)
    grouped = {}
    for row in rows:
        aid = str(row.get("adapter_id") or "")
        grouped.setdefault(aid, []).append(row)
    return {"adapters": grouped, "count": len(rows)}


@router.post("/finetune/adapters")
async def create_finetune_adapter_version(request: Request):
    from ..db import save_lora_adapter_version

    body = await _read_json_body(request, "invalid JSON body")
    adapter_id = str(body.get("adapter_id") or "").strip()
    version = str(body.get("version") or "").strip()
    base_model = str(body.get("base_model") or "nexus-prime-base").strip()
    checkpoint_uri = str(body.get("checkpoint_uri") or "").strip()
    if not adapter_id:
        return _api_error("adapter_id is required", "validation_error", 422)
    if not version:
        return _api_error("version is required", "validation_error", 422)
    if not checkpoint_uri:
        return _api_error("checkpoint_uri is required", "validation_error", 422)

    rec = save_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        base_model=base_model,
        checkpoint_uri=checkpoint_uri,
        metrics=body.get("metrics") if isinstance(body.get("metrics"), dict) else {},
        provenance=body.get("provenance") if isinstance(body.get("provenance"), dict) else {},
        tags=body.get("tags") if isinstance(body.get("tags"), list) else [],
        status=str(body.get("status") or "ready"),
    )
    return {"adapter": rec}


@router.get("/finetune/adapters/{adapter_id}")
def get_finetune_adapter(adapter_id: str):
    from ..db import get_lora_adapter_version, list_lora_adapter_versions

    latest = get_lora_adapter_version(adapter_id=adapter_id)
    if latest is None:
        return _api_error("adapter not found", "not_found", 404)
    versions = list_lora_adapter_versions(adapter_id=adapter_id)
    return {"adapter_id": adapter_id, "latest": latest, "versions": versions}


@router.get("/finetune/adapters/{adapter_id}/versions/{version}")
def get_finetune_adapter_version(adapter_id: str, version: str):
    from ..db import get_lora_adapter_version

    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)
    return {"adapter": row}


@router.get("/finetune/adapters/{adapter_id}/compare")
def compare_finetune_adapter_versions(adapter_id: str, left: str = "", right: str = ""):
    from ..db import compare_lora_adapter_versions

    if not left or not right:
        return _api_error("left and right version params are required", "validation_error", 422)
    diff = compare_lora_adapter_versions(adapter_id=adapter_id, left_version=left, right_version=right)
    if diff is None:
        return _api_error("adapter/version pair not found", "not_found", 404)
    return diff


@router.get("/finetune/adapters/{adapter_id}/proof-reports")
def list_finetune_adapter_proof_reports(adapter_id: str, version: str = "", limit: int = 20):
    from ..db import list_adapter_proof_reports

    rows = list_adapter_proof_reports(adapter_id=adapter_id, adapter_version=version, limit=limit)
    return {"proof_reports": rows, "count": len(rows)}


@router.post("/finetune/adapters/{adapter_id}/proof")
async def run_finetune_adapter_proof(adapter_id: str, request: Request):
    from ..db import get_lora_adapter_version
    from ..eval_pipeline import run_adapter_proof_report

    body = await _read_json_body(request, "invalid JSON body")
    version = str(body.get("version") or "").strip()
    if not version:
        return _api_error("version is required", "validation_error", 422)

    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    try:
        report = run_adapter_proof_report(
            base_model=str(body.get("base_model") or row.get("base_model") or "nexus-prime-base"),
            adapter_id=adapter_id,
            adapter_version=version,
            provider=str(body.get("provider") or "offline"),
            suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
            n_samples=int(body.get("n_samples") or 20),
            min_improvement=float(body.get("min_improvement") or 0.01),
            max_regressions=int(body.get("max_regressions") or 0),
            regression_threshold=float(body.get("regression_threshold") or 0.05),
        )
        return {"proof_report": report}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/finetune/adapters/{adapter_id}/promote")
async def promote_finetune_adapter(adapter_id: str, request: Request):
    from ..db import (
        get_adapter_proof_report,
        get_lora_adapter_version,
        list_adapter_proof_reports,
        update_lora_adapter_version,
    )

    body = await _read_json_body(request, "invalid JSON body")
    version = str(body.get("version") or "").strip()
    if not version:
        return _api_error("version is required", "validation_error", 422)

    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    report_id = str(body.get("report_id") or "").strip()
    proof_report = get_adapter_proof_report(report_id) if report_id else None
    if proof_report is None:
        reports = list_adapter_proof_reports(adapter_id=adapter_id, adapter_version=version, limit=1)
        proof_report = reports[0] if reports else None
    if proof_report is None:
        return _api_error("no proof report found for adapter promotion", "proof_required", 409)
    if not bool(proof_report.get("passes", False)):
        return _api_error("adapter promotion blocked by proof gate", "proof_gate_failed", 409)

    updated = update_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        updates={
            "status": "promoted",
            "promotion_report_id": proof_report.get("report_id"),
            "promoted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )
    return {"promoted": True, "adapter": updated, "proof_report": proof_report}


@router.post("/finetune/adapters/{adapter_id}/hot-swap")
async def hot_swap_finetune_adapter(adapter_id: str, request: Request):
    from ..db import get_lora_adapter_version, set_active_lora_adapter

    body = await _read_json_body(request, "invalid JSON body")
    if adapter_id == "multitask":
        from ..db import get_multitask_adapter_map, save_multitask_adapter_map

        task_name = str(body.get("task") or "").strip().lower()
        selected_adapter_id = str(body.get("adapter_id") or "").strip()
        selected_version = str(body.get("version") or "").strip()
        target_model = str(body.get("target_model") or "").strip()
        if not task_name or not selected_adapter_id or not selected_version:
            return _api_error("task, adapter_id and version are required", "validation_error", 422)

        selected = get_lora_adapter_version(adapter_id=selected_adapter_id, version=selected_version)
        if selected is None:
            return _api_error("adapter version not found", "not_found", 404)

        target_for_gate = target_model or str(selected.get("base_model") or "nexus-prime-base")
        gate_enabled = bool(body.get("run_regression_gate", True))
        gate_enforced = bool(body.get("enforce_regression_gate", True))
        regression_gate = None
        if gate_enabled:
            regression_gate = _run_model_update_regression_gate(
                model=target_for_gate,
                provider=str(body.get("provider") or "ollama"),
                suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
                threshold=float(body.get("threshold") or 0.05),
                n_samples=int(body.get("n_samples") or 8),
                enforce=gate_enforced,
            )
            if not bool(regression_gate.get("allowed", True)):
                return _api_error("regression gate blocked multitask adapter hot-swap", "regression_gate_failed", 409)

        current = get_multitask_adapter_map()
        mapping = current.get("mapping") if isinstance(current.get("mapping"), dict) else {}
        mapping[task_name] = {
            "adapter_id": selected_adapter_id,
            "version": selected_version,
            "target_model": target_model,
        }
        multitask = save_multitask_adapter_map(mapping)
        active = set_active_lora_adapter(
            adapter_id=selected_adapter_id,
            version=selected_version,
            target_model=target_model,
        )
        return {
            "task": task_name,
            "swapped": True,
            "active_adapter": active,
            "multitask_adapters": multitask,
            "adapter": selected,
            "regression_gate": regression_gate,
        }

    version = str(body.get("version") or "").strip()
    target_model = str(body.get("target_model") or "").strip()
    if not version:
        return _api_error("version is required", "validation_error", 422)
    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    target_for_gate = target_model or str(row.get("base_model") or "nexus-prime-base")
    gate_enabled = bool(body.get("run_regression_gate", True))
    gate_enforced = bool(body.get("enforce_regression_gate", True))
    regression_gate = None
    if gate_enabled:
        regression_gate = _run_model_update_regression_gate(
            model=target_for_gate,
            provider=str(body.get("provider") or "ollama"),
            suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
            threshold=float(body.get("threshold") or 0.05),
            n_samples=int(body.get("n_samples") or 8),
            enforce=gate_enforced,
        )
        if not bool(regression_gate.get("allowed", True)):
            return _api_error("regression gate blocked adapter hot-swap", "regression_gate_failed", 409)

    active = set_active_lora_adapter(adapter_id=adapter_id, version=version, target_model=target_model)
    return {
        "swapped": True,
        "active_adapter": active,
        "adapter": row,
        "note": "Hot-swap state recorded. Runtime model application is provider-dependent.",
        "regression_gate": regression_gate,
    }
@router.get("/finetune/datasets/versions")
def list_finetune_dataset_versions(limit: int = 100):
    from ..db import list_ft_dataset_versions

    rows = list_ft_dataset_versions(limit=limit)
    return {"dataset_versions": rows, "count": len(rows)}


@router.get("/finetune/datasets/versions/{dataset_id}")
def get_finetune_dataset_version(dataset_id: str):
    from ..db import get_ft_dataset_version

    row = get_ft_dataset_version(dataset_id)
    if row is None:
        return _api_error("dataset version not found", "not_found", 404)
    return {"dataset_version": row}


@router.post("/finetune/one-click")
async def one_click_finetune_from_feedback(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    include_trace = bool(body.get("include_trace", True))
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    limit = max(1, min(int(body.get("limit") or 5000), 20000))

    rows = _training_rows_from_feedback(include_trace=include_trace, limit=limit)
    if not rows:
        return _api_error("no feedback/trace rows available", "validation_error", 422)

    return _create_finetune_job_from_rows(
        model=model,
        rows=rows,
        source="feedback_trace",
        provenance_extra={"include_trace": include_trace},
    )


@router.post("/finetune/synthetic/generate")
async def generate_synthetic_training_data(request: Request):
    from ..db import save_synthetic_batch
    from ..simulation import SimulationEngine, export_training_dataset

    body = await _read_json_body(request, "invalid JSON body")
    topic = str(body.get("topic") or "Sovereign AI assistant capabilities").strip()
    seed = str(body.get("seed") or "").strip()
    n_samples = max(1, min(int(body.get("n_samples") or 16), 200))
    n_personas = max(2, min(int(body.get("n_personas") or 5), 8))
    n_rounds = max(1, min(int(body.get("n_rounds") or 3), 5))
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    include_vision = bool(body.get("include_vision", False))

    def _sim_llm(msgs):
        try:
            res, _ = call_llm_with_fallback(msgs, "synthetic_training_generation")
            if isinstance(res, dict):
                if res.get("action") == "respond":
                    return str(res.get("content") or "")
                return json.dumps(res)
            return str(res)
        except Exception:
            return "{\"statement\": \"Fallback synthetic statement\"}"

    rows: list[dict] = []
    try:
        engine = SimulationEngine(_sim_llm, max_personas=8, max_rounds=5)
        target_runs = max(1, min(n_samples // 4, 6))
        for idx in range(target_runs):
            sim = engine.run(
                topic=f"{topic} :: scenario {idx + 1}",
                seed=seed,
                n_personas=n_personas,
                n_rounds=n_rounds,
            )
            exported = export_training_dataset([sim.to_dict()])
            for item in exported:
                prompt = str(item.get("prompt") or "").strip()
                response = str(item.get("response") or "").strip()
                if not prompt or not response:
                    continue
                rows.append(
                    {
                        "prompt": prompt,
                        "response": response,
                        "source": "synthetic_swarm",
                        "topic": topic,
                        "modality": "vision_text" if include_vision else "text",
                    }
                )
                if len(rows) >= n_samples:
                    break
            if len(rows) >= n_samples:
                break
    except Exception:
        rows = []

    while len(rows) < n_samples:
        idx = len(rows) + 1
        rows.append(
            {
                "prompt": f"[{topic}] Generate a high-quality instruction #{idx} with grounded reasoning.",
                "response": (
                    f"Instruction #{idx} answer synthesized from multi-agent debate on {topic}. "
                    "Provide rationale, constraints, and verification steps."
                ),
                "source": "synthetic_swarm",
                "topic": topic,
                "modality": "vision_text" if include_vision else "text",
            }
        )

    for row in rows:
        db_save_ft_training_sample(
            task=str(row.get("prompt") or ""),
            result=str(row.get("response") or ""),
            quality=0.78,
            lessons=["synthetic", "agent_swarm"],
            source="synthetic_swarm",
        )

    bundle = _create_finetune_job_from_rows(
        model=model,
        rows=rows,
        source="synthetic",
        provenance_extra={
            "topic": topic,
            "seed": seed[:400],
            "n_personas": n_personas,
            "n_rounds": n_rounds,
            "include_vision": include_vision,
        },
    )
    batch_id = f"syn-{uuid.uuid4().hex[:10]}"
    batch = save_synthetic_batch(
        batch_id=batch_id,
        topic=topic,
        row_count=len(rows),
        params={
            "n_samples": n_samples,
            "n_personas": n_personas,
            "n_rounds": n_rounds,
            "include_vision": include_vision,
        },
        dataset_id=str(bundle.get("dataset_version", {}).get("dataset_id") or ""),
    )
    return {"batch": batch, **bundle}


@router.get("/finetune/synthetic/batches")
def list_synthetic_training_batches(limit: int = 100):
    from ..db import list_synthetic_batches

    rows = list_synthetic_batches(limit=max(1, min(int(limit or 100), 500)))
    return {"batches": rows, "count": len(rows)}


@router.get("/finetune/curation/samples")
def list_curation_samples(limit: int = 100, min_quality: float = 0.0, source: str = "", approved: str = "", label: str = ""):
    from ..db import list_ft_sample_curation

    samples = db_list_ft_training_samples(limit=max(1, min(int(limit or 100), 1000)), min_quality=float(min_quality or 0.0))
    curation_map = list_ft_sample_curation()

    merged = []
    for row in samples:
        sample_id = str(row.get("id") or "")
        curation = curation_map.get(sample_id, {})
        if source and str(row.get("source") or "") != source:
            continue
        if approved.strip().lower() in {"true", "false"}:
            want = approved.strip().lower() == "true"
            if bool(curation.get("approved")) != want:
                continue
        if label and str(curation.get("label") or "").strip().lower() != label.strip().lower():
            continue
        merged.append({**row, "curation": curation})

    return {"samples": merged, "count": len(merged)}


@router.post("/finetune/curation/samples/{sample_id}/review")
async def review_curation_sample(sample_id: str, request: Request):
    from ..db import get_ft_sample_curation, upsert_ft_sample_curation

    body = await _read_json_body(request, "invalid JSON body")
    approved = body.get("approved")
    approved_val = bool(approved) if approved is not None else None
    label = str(body.get("label") or "").strip()
    notes = str(body.get("notes") or "").strip()
    reviewer = str(body.get("reviewer") or "system").strip() or "system"
    previous = get_ft_sample_curation(sample_id)
    row = upsert_ft_sample_curation(
        sample_id=sample_id,
        approved=approved_val,
        label=label,
        notes=notes,
        reviewer=reviewer,
    )
    return {"curation": row, "previous": previous}


@router.post("/finetune/curation/samples/bulk-approve")
async def bulk_approve_curation_samples(request: Request):
    from ..db import upsert_ft_sample_curation

    body = await _read_json_body(request, "invalid JSON body")
    sample_ids = body.get("sample_ids") if isinstance(body.get("sample_ids"), list) else []
    label = str(body.get("label") or "approved").strip()
    reviewer = str(body.get("reviewer") or "system").strip() or "system"
    updated = []
    for sample_id in sample_ids:
        sid = str(sample_id or "").strip()
        if not sid:
            continue
        updated.append(
            upsert_ft_sample_curation(
                sample_id=sid,
                approved=True,
                label=label,
                reviewer=reviewer,
            )
        )
    return {"updated": updated, "count": len(updated)}


@router.get("/finetune/curation/ui")
def finetune_curation_ui():
    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
        <title>Fine-tune Curation</title>
      </head>
      <body style=\"font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 24px;\">
        <h1>Training Sample Curation</h1>
        <p>Use API-backed filtering and one-click approval for Section 12 curation.</p>
        <button onclick=\"load()\">Reload Samples</button>
        <div id=\"count\" style=\"margin-top:12px;\"></div>
        <table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" style=\"margin-top:12px;width:100%;\">
          <thead><tr><th>ID</th><th>Source</th><th>Quality</th><th>Task</th><th>Approved</th><th>Label</th></tr></thead>
          <tbody id=\"rows\"></tbody>
        </table>
        <script>
          async function load() {
            const res = await fetch('/finetune/curation/samples?limit=50&min_quality=0.5');
            const data = await res.json();
            document.getElementById('count').textContent = `Loaded ${data.count || 0} samples`;
            const tbody = document.getElementById('rows');
            tbody.innerHTML = '';
            for (const s of (data.samples || [])) {
              const tr = document.createElement('tr');
              tr.innerHTML = `<td>${s.id}</td><td>${s.source || ''}</td><td>${(s.quality || 0).toFixed ? s.quality.toFixed(2) : s.quality}</td><td>${(s.task || '').slice(0,120)}</td><td>${s.curation?.approved === true}</td><td>${s.curation?.label || ''}</td>`;
              tbody.appendChild(tr);
            }
          }
          load();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/finetune/adapters/multitask")
def get_multitask_adapters():
    from ..db import get_multitask_adapter_map

    return get_multitask_adapter_map()


@router.post("/finetune/adapters/multitask")
async def set_multitask_adapters(request: Request):
    from ..db import get_lora_adapter_version, save_multitask_adapter_map

    body = await _read_json_body(request, "invalid JSON body")
    mapping = body.get("mapping") if isinstance(body.get("mapping"), dict) else {}
    normalized = {}
    for task_name, row in mapping.items():
        if not isinstance(row, dict):
            continue
        adapter_id = str(row.get("adapter_id") or "").strip()
        version = str(row.get("version") or "").strip()
        if not adapter_id or not version:
            continue
        if get_lora_adapter_version(adapter_id=adapter_id, version=version) is None:
            continue
        normalized[str(task_name).strip().lower()] = {
            "adapter_id": adapter_id,
            "version": version,
            "target_model": str(row.get("target_model") or "").strip(),
        }
    saved = save_multitask_adapter_map(normalized)
    return {"multitask_adapters": saved}


@router.post("/finetune/adapters/multitask/hot-swap")
async def hot_swap_multitask_adapter(request: Request):
    from ..db import get_lora_adapter_version, get_multitask_adapter_map, save_multitask_adapter_map, set_active_lora_adapter

    body = await _read_json_body(request, "invalid JSON body")
    task_name = str(body.get("task") or "").strip().lower()
    adapter_id = str(body.get("adapter_id") or "").strip()
    version = str(body.get("version") or "").strip()
    target_model = str(body.get("target_model") or "").strip()
    if not task_name or not adapter_id or not version:
        return _api_error("task, adapter_id and version are required", "validation_error", 422)
    row = get_lora_adapter_version(adapter_id=adapter_id, version=version)
    if row is None:
        return _api_error("adapter version not found", "not_found", 404)

    current = get_multitask_adapter_map()
    mapping = current.get("mapping") if isinstance(current.get("mapping"), dict) else {}
    mapping[task_name] = {
        "adapter_id": adapter_id,
        "version": version,
        "target_model": target_model,
    }
    saved = save_multitask_adapter_map(mapping)
    active = set_active_lora_adapter(adapter_id=adapter_id, version=version, target_model=target_model)
    return {"task": task_name, "active_adapter": active, "multitask_adapters": saved, "adapter": row}

@router.post("/finetune/multimodal/jobs")
async def create_multimodal_finetune_job(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    rows = body.get("rows") if isinstance(body.get("rows"), list) else []
    if not rows:
        return _api_error("rows is required and must be a non-empty list", "validation_error", 422)

    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        prompt = str(row.get("prompt") or "").strip()
        response = str(row.get("response") or "").strip()
        image_url = str(row.get("image_url") or "").strip()
        image_b64 = str(row.get("image_b64") or "").strip()
        if not prompt or not response:
            continue
        if not image_url and not image_b64:
            continue
        normalized.append(
            {
                "prompt": prompt,
                "response": response,
                "image_url": image_url,
                "image_b64": bool(image_b64),
                "source": "multimodal_vision",
                "modality": "vision_text",
            }
        )

    if not normalized:
        return _api_error("no valid multimodal rows (requires prompt, response, image_url/image_b64)", "validation_error", 422)

    return _create_finetune_job_from_rows(
        model=model,
        rows=normalized,
        source="multimodal_vision",
        provenance_extra={"multimodal": True, "modality": "vision_text"},
    )
def _run_distill_job(job_id: str):
    from ..db import (
        append_distill_job_event,
        get_distill_job,
        save_lora_adapter_version,
        update_distill_job,
    )

    job = get_distill_job(job_id)
    if not job or str(job.get("status") or "") != "queued":
        return

    append_distill_job_event(job_id, "Distillation job started")
    update_distill_job(job_id, status="running")
    teacher = str(job.get("teacher_model") or "")
    student = str(job.get("student_model") or "nexus-prime-base")
    provider = str(job.get("provider") or "auto")
    cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
    prompts = cfg.get("prompts") if isinstance(cfg.get("prompts"), list) else []
    if not prompts:
        prompts = [
            "Explain how adapter hot-swap works in a sovereign deployment.",
            "Design a retry-safe continual fine-tune policy.",
            "Summarize RLHF vs DPO tradeoffs for local models.",
            "Provide robust guardrails for tool execution in an agent loop.",
        ]

    rows: list[dict] = []
    for prompt in prompts[:50]:
        p = str(prompt or "").strip()
        if not p:
            continue
        teacher_answer = ""
        try:
            teacher_messages = [{"role": "user", "content": p}]
            answer, _used_provider = call_llm_with_fallback(teacher_messages, "distillation", provider)
            if isinstance(answer, dict):
                teacher_answer = str(answer.get("content") or answer.get("result") or "").strip()
            else:
                teacher_answer = str(answer or "").strip()
        except Exception:
            teacher_answer = ""
        if not teacher_answer:
            teacher_answer = f"Teacher synthesis for: {p}"
        rows.append({"prompt": p, "response": teacher_answer, "source": "distillation", "teacher_model": teacher})

    if not rows:
        update_distill_job(job_id, status="failed", error={"message": "no distillation rows generated"})
        append_distill_job_event(job_id, "No rows generated", level="error")
        return

    bundle = _create_finetune_job_from_rows(
        model=student,
        rows=rows,
        source="distillation",
        provenance_extra={"teacher_model": teacher, "provider": provider, "distill_job_id": job_id},
    )
    ft_job_id = str(bundle.get("job", {}).get("id") or "")
    append_distill_job_event(job_id, "Fine-tune child job created", data={"fine_tune_job_id": ft_job_id})

    timeout_s = max(30, min(int(cfg.get("timeout_seconds") or 600), 3600))
    started = time.time()
    while time.time() - started <= timeout_s:
        current = get_distill_job(job_id)
        if not current or str(current.get("status") or "") == "cancelled":
            append_distill_job_event(job_id, "Distillation cancelled")
            return
        ft_job = db_get_fine_tuning_job(ft_job_id)
        if ft_job and str(ft_job.get("status") or "") in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.4)

    ft_job = db_get_fine_tuning_job(ft_job_id)
    status = str(ft_job.get("status") or "") if isinstance(ft_job, dict) else "failed"
    if status != "succeeded":
        update_distill_job(job_id, status="failed", error={"message": f"child fine-tune ended with {status}"})
        append_distill_job_event(job_id, "Child fine-tune failed", level="error", data={"status": status})
        return

    adapter_id = f"distill-{student.replace('/', '-') }"
    version = f"v{int(time.time())}"
    adapter = save_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        base_model=student,
        checkpoint_uri=f"inline://adapters/{adapter_id}/{version}",
        metrics={"trained_tokens": int(ft_job.get("trained_tokens") or 0)},
        provenance={
            "distill_job_id": job_id,
            "teacher_model": teacher,
            "dataset_version_id": str(bundle.get("dataset_version", {}).get("dataset_id") or ""),
        },
        tags=["distillation", "student"],
        status="ready",
    )
    result = {
        "fine_tune_job_id": ft_job_id,
        "dataset_version": bundle.get("dataset_version", {}),
        "adapter": adapter,
    }
    update_distill_job(job_id, status="succeeded", result=result, error=None)
    append_distill_job_event(job_id, "Distillation completed", data=result)


@router.post("/finetune/distill/jobs")
async def create_distillation_job(request: Request):
    from ..db import create_distill_job

    body = await _read_json_body(request, "invalid JSON body")
    teacher_model = str(body.get("teacher_model") or "").strip()
    student_model = str(body.get("student_model") or "nexus-prime-base").strip() or "nexus-prime-base"
    provider = str(body.get("provider") or "auto").strip() or "auto"
    if not teacher_model:
        return _api_error("teacher_model is required", "validation_error", 422)
    job = create_distill_job(
        teacher_model=teacher_model,
        student_model=student_model,
        provider=provider,
        config=body.get("config") if isinstance(body.get("config"), dict) else {},
    )
    threading.Thread(target=_run_distill_job, args=(job["id"],), daemon=True).start()
    return {"job": job}


@router.get("/finetune/distill/jobs")
def list_distillation_jobs(limit: int = 100):
    from ..db import list_distill_jobs

    rows = list_distill_jobs(limit=max(1, min(int(limit or 100), 500)))
    return {"jobs": rows, "count": len(rows)}


@router.get("/finetune/distill/jobs/{job_id}")
def get_distillation_job(job_id: str):
    from ..db import get_distill_job

    row = get_distill_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    return {"job": row}


@router.post("/finetune/distill/jobs/{job_id}/cancel")
def cancel_distillation_job(job_id: str):
    from ..db import get_distill_job, update_distill_job

    row = get_distill_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    if str(row.get("status") or "") not in {"succeeded", "failed", "cancelled"}:
        row = update_distill_job(job_id, status="cancelled", error={"message": "Cancelled by user"}) or row
    return {"job": row}
def _nexus_prime_alpha_wire_key() -> str:
    return "finetune.persona.nexus_prime_alpha.v1"


@router.get("/finetune/personas/nexus-prime-alpha/wire")
def get_nexus_prime_alpha_wiring():
    raw = db_load_pref(_nexus_prime_alpha_wire_key(), "{}")
    try:
        row = json.loads(raw)
        if not isinstance(row, dict):
            row = {}
    except Exception:
        row = {}
    return {"wiring": row}


@router.post("/finetune/personas/nexus-prime-alpha/wire")
async def wire_nexus_prime_alpha_persona(request: Request):
    from ..db import get_lora_adapter_version, set_active_lora_adapter

    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-alpha").strip() or "nexus-prime-alpha"
    adapter_id = str(body.get("adapter_id") or "").strip()
    adapter_version = str(body.get("adapter_version") or "").strip()
    provider_order = body.get("provider_order") if isinstance(body.get("provider_order"), list) else ["ollama", "llm7", "groq"]

    gate_enabled = bool(body.get("run_regression_gate", True))
    gate_enforced = bool(body.get("enforce_regression_gate", True))
    regression_gate = None
    if gate_enabled:
        regression_gate = _run_model_update_regression_gate(
            model=model,
            provider=str(body.get("provider") or "ollama"),
            suites=body.get("suites") if isinstance(body.get("suites"), list) else None,
            threshold=float(body.get("threshold") or 0.05),
            n_samples=int(body.get("n_samples") or 8),
            enforce=gate_enforced,
        )
        if not bool(regression_gate.get("allowed", True)):
            return _api_error("regression gate blocked nexus-prime-alpha wiring", "regression_gate_failed", 409)

    set_persona("nexus_prime_alpha")
    update_config(persona="nexus_prime_alpha", model=model)
    set_provider_persona_override("nexus_prime_alpha", [str(p).strip() for p in provider_order if str(p).strip()])

    active_adapter = {}
    if adapter_id and adapter_version:
        row = get_lora_adapter_version(adapter_id=adapter_id, version=adapter_version)
        if row is None:
            return _api_error("adapter not found", "not_found", 404)
        active_adapter = set_active_lora_adapter(adapter_id=adapter_id, version=adapter_version, target_model=model)

    wiring = {
        "persona": "nexus_prime_alpha",
        "model": model,
        "provider_order": provider_order,
        "active_adapter": active_adapter,
        "regression_gate": regression_gate,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    db_save_pref(_nexus_prime_alpha_wire_key(), json.dumps(wiring))
    return {"wired": True, "wiring": wiring}
def _run_rlhf_dpo_job(job_id: str):
    from ..db import (
        append_rlhf_dpo_job_event,
        get_ft_dataset_version,
        get_rlhf_dpo_job,
        save_lora_adapter_version,
        update_rlhf_dpo_job,
    )
    from ..eval_pipeline import score_response
    from ..rlhf_dpo import (
        create_dpo_job as _create_native_dpo_job,
        create_rlhf_job as _create_native_rlhf_job,
        run_dpo_training as _run_native_dpo_training,
        run_rlhf_training as _run_native_rlhf_training,
    )

    def _build_preference_pair(row: dict) -> dict | None:
        prompt = str(row.get("prompt") or row.get("instruction") or "").strip()
        if not prompt:
            return None
        chosen = str(row.get("chosen") or row.get("response") or row.get("output") or "").strip()
        if not chosen:
            return None
        rejected = str(row.get("rejected") or "").strip()
        synthetic_negative = False
        if not rejected:
            synthetic_negative = True
            words = chosen.split()
            if len(words) > 6:
                rejected = " ".join(words[: max(3, len(words) // 3)])
            else:
                rejected = "Insufficient or incomplete answer."
        return {
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "synthetic_negative": synthetic_negative,
        }

    def _score_preference_pairs(pairs: list[dict]) -> dict:
        scored_rows: list[dict] = []
        chosen_total = 0.0
        rejected_total = 0.0
        margin_total = 0.0
        synthetic_negative_count = 0
        for idx, pair in enumerate(pairs, start=1):
            prompt = str(pair.get("prompt") or "")
            chosen = str(pair.get("chosen") or "")
            rejected = str(pair.get("rejected") or "")
            synthetic_negative = bool(pair.get("synthetic_negative"))
            if synthetic_negative:
                synthetic_negative_count += 1
            chosen_score = float(score_response(prompt, chosen, reference=chosen).get("score") or 0.0)
            rejected_score = float(score_response(prompt, rejected, reference=chosen).get("score") or 0.0)
            margin = round(chosen_score - rejected_score, 6)
            chosen_total += chosen_score
            rejected_total += rejected_score
            margin_total += margin
            scored_rows.append(
                {
                    "pair_id": idx,
                    "prompt": prompt,
                    "chosen_score": round(chosen_score, 6),
                    "rejected_score": round(rejected_score, 6),
                    "margin": margin,
                    "synthetic_negative": synthetic_negative,
                    "passed": margin > 0,
                }
            )

        pair_count = len(scored_rows)
        return {
            "pair_count": pair_count,
            "synthetic_negative_count": synthetic_negative_count,
            "chosen_avg": round(chosen_total / max(1, pair_count), 6),
            "rejected_avg": round(rejected_total / max(1, pair_count), 6),
            "preference_alignment_score": round(margin_total / max(1, pair_count), 6),
            "rows": scored_rows,
        }

    job = get_rlhf_dpo_job(job_id)
    if not job:
        return
    if str(job.get("status") or "") != "queued":
        return

    append_rlhf_dpo_job_event(job_id, "RLHF/DPO job started")
    update_rlhf_dpo_job(job_id, status="running", error=None)

    latest = get_rlhf_dpo_job(job_id)
    if not latest:
        return
    if str(latest.get("status") or "") == "cancelled":
        append_rlhf_dpo_job_event(job_id, "RLHF/DPO job cancelled before execution")
        return

    method = str(latest.get("method") or "dpo")
    base_model = str(latest.get("base_model") or "nexus-prime-base")
    dataset_version_id = str(latest.get("dataset_version_id") or "")
    config = latest.get("config") if isinstance(latest.get("config"), dict) else {}
    training_backend = str(config.get("training_backend") or "orchestration").strip().lower()
    if training_backend not in {"orchestration", "native"}:
        training_backend = "orchestration"
    telemetry_gates = {
        "min_pair_count": max(1, int(config.get("gate_min_pair_count") or 8)),
        "min_alignment_score": float(config.get("gate_min_alignment_score") or 0.02),
        "max_synthetic_negative_ratio": float(config.get("gate_max_synthetic_negative_ratio") or 0.75),
    }
    dataset = get_ft_dataset_version(dataset_version_id)
    if dataset is None:
        update_rlhf_dpo_job(job_id, status="failed", error={"message": "dataset_version_id not found"})
        append_rlhf_dpo_job_event(job_id, "Dataset not found", level="error", data={"dataset_version_id": dataset_version_id})
        return

    preview_rows = dataset.get("preview_rows") if isinstance(dataset.get("preview_rows"), list) else []
    preference_pairs = []
    for row in preview_rows[:200]:
        if isinstance(row, dict):
            pair = _build_preference_pair(row)
            if pair is not None:
                preference_pairs.append(pair)
    if not preference_pairs:
        update_rlhf_dpo_job(job_id, status="failed", error={"message": "dataset_version_id contains no usable preference rows"})
        append_rlhf_dpo_job_event(job_id, "No usable preference rows found", level="error", data={"dataset_version_id": dataset_version_id})
        return

    preference_metrics = _score_preference_pairs(preference_pairs)
    synthetic_ratio = float(preference_metrics["synthetic_negative_count"]) / max(1, float(preference_metrics["pair_count"]))
    gate_fail_reasons: list[str] = []
    if int(preference_metrics["pair_count"]) < int(telemetry_gates["min_pair_count"]):
        gate_fail_reasons.append(
            f"pair_count={preference_metrics['pair_count']} < min_pair_count={telemetry_gates['min_pair_count']}"
        )
    if float(preference_metrics["preference_alignment_score"]) < float(telemetry_gates["min_alignment_score"]):
        gate_fail_reasons.append(
            "preference_alignment_score="
            f"{preference_metrics['preference_alignment_score']} < min_alignment_score={telemetry_gates['min_alignment_score']}"
        )
    if synthetic_ratio > float(telemetry_gates["max_synthetic_negative_ratio"]):
        gate_fail_reasons.append(
            f"synthetic_negative_ratio={round(synthetic_ratio, 6)} > "
            f"max_synthetic_negative_ratio={telemetry_gates['max_synthetic_negative_ratio']}"
        )

    append_rlhf_dpo_job_event(
        job_id,
        "RLHF/DPO telemetry gates evaluated",
        data={
            "training_backend": training_backend,
            "telemetry_gates": telemetry_gates,
            "pair_count": preference_metrics["pair_count"],
            "preference_alignment_score": preference_metrics["preference_alignment_score"],
            "synthetic_negative_ratio": round(synthetic_ratio, 6),
            "gate_fail_reasons": gate_fail_reasons,
        },
    )

    if gate_fail_reasons:
        update_rlhf_dpo_job(
            job_id,
            status="failed",
            error={"message": "telemetry gates failed", "reasons": gate_fail_reasons},
            result={
                "training_backend": training_backend,
                "telemetry_gates": telemetry_gates,
                "pair_count": preference_metrics["pair_count"],
                "preference_alignment_score": preference_metrics["preference_alignment_score"],
                "synthetic_negative_ratio": round(synthetic_ratio, 6),
            },
        )
        append_rlhf_dpo_job_event(job_id, "RLHF/DPO telemetry gates failed", level="error", data={"reasons": gate_fail_reasons})
        return

    native_training_result: dict | None = None

    if training_backend == "native":
        import tempfile as _tempfile

        tmp_ds = os.path.join(_tempfile.gettempdir(), f"nexus_rlhf_dpo_{job_id}.jsonl")
        with open(tmp_ds, "w", encoding="utf-8") as f:
            for pair in preference_pairs:
                f.write(
                    json.dumps(
                        {
                            "prompt": pair["prompt"],
                            "chosen": pair["chosen"],
                            "rejected": pair["rejected"],
                            "margin": max(0.0, float(preference_metrics["preference_alignment_score"])),
                            "source": "rlhf_dpo_experiment",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        append_rlhf_dpo_job_event(
            job_id,
            "Native RLHF/DPO backend selected",
            data={"dataset_path": str(tmp_ds), "method": method},
        )

        if method == "dpo":
            native_job = _create_native_dpo_job(
                base_model=base_model,
                dataset_path=str(tmp_ds),
                adapter_name=f"{base_model.replace('/', '-')}-dpo-native",
                config=config,
            )
            _run_native_dpo_training(native_job)
            if native_job.status != "completed":
                update_rlhf_dpo_job(
                    job_id,
                    status="failed",
                    error={"message": f"native DPO backend failed: {native_job.error or native_job.status}"},
                )
                append_rlhf_dpo_job_event(job_id, "Native DPO backend failed", level="error", data={"job_id": native_job.job_id, "error": native_job.error})
                return
            native_training_result = {
                "native_job_id": native_job.job_id,
                "native_backend": "dpo",
                "adapter_path": native_job.adapter_path,
                "metrics": native_job.metrics,
            }
        else:
            native_job = _create_native_rlhf_job(
                base_model=base_model,
                dataset_path=str(tmp_ds),
                adapter_name=f"{base_model.replace('/', '-')}-rlhf-native",
                config=config,
            )
            _run_native_rlhf_training(native_job)
            if native_job.status != "completed":
                update_rlhf_dpo_job(
                    job_id,
                    status="failed",
                    error={"message": f"native RLHF backend failed: {native_job.error or native_job.status}"},
                )
                append_rlhf_dpo_job_event(job_id, "Native RLHF backend failed", level="error", data={"job_id": native_job.job_id, "error": native_job.error})
                return
            native_training_result = {
                "native_job_id": native_job.job_id,
                "native_backend": "rlhf",
                "adapter_path": native_job.adapter_path,
                "metrics": native_job.metrics,
                "rounds_completed": native_job.rounds_completed,
            }

    if training_backend == "orchestration":

        child = _create_finetune_job_from_rows(
        model=base_model,
        rows=[
            {
                "prompt": pair["prompt"],
                "response": pair["chosen"],
                "source": "rlhf_dpo",
                "preference_rejected": pair["rejected"],
                "synthetic_negative": pair["synthetic_negative"],
            }
            for pair in preference_pairs
        ],
        source="rlhf_dpo",
        provenance_extra={
            "method": method,
            "dataset_version_id": dataset_version_id,
            "rlhf_dpo_job_id": job_id,
            "config": latest.get("config") if isinstance(latest.get("config"), dict) else {},
            "pair_count": preference_metrics["pair_count"],
            "synthetic_negative_count": preference_metrics["synthetic_negative_count"],
        },
    )
        fine_tune_job_id = str(child.get("job", {}).get("id") or "")
        append_rlhf_dpo_job_event(job_id, "Fine-tune child job created", data={"fine_tune_job_id": fine_tune_job_id})

        timeout_seconds = 900
        started_at = time.time()
        while time.time() - started_at <= timeout_seconds:
            current = get_rlhf_dpo_job(job_id)
            if not current or str(current.get("status") or "") == "cancelled":
                append_rlhf_dpo_job_event(job_id, "RLHF/DPO job cancelled")
                return
            ft_job = db_get_fine_tuning_job(fine_tune_job_id)
            if ft_job and str(ft_job.get("status") or "") in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.4)

        ft_job = db_get_fine_tuning_job(fine_tune_job_id)
        if not ft_job:
            update_rlhf_dpo_job(job_id, status="failed", error={"message": "fine-tune child job missing"})
            append_rlhf_dpo_job_event(job_id, "Child fine-tune job missing", level="error")
            return
        ft_status = str(ft_job.get("status") or "")
        if ft_status != "succeeded":
            update_rlhf_dpo_job(
                job_id,
                status="failed",
                error={"message": f"fine-tune child job ended with status={ft_status}"},
                result={"fine_tune_job_id": fine_tune_job_id, "dataset_version_id": dataset_version_id},
            )
            append_rlhf_dpo_job_event(job_id, "Child fine-tune failed", level="error", data={"status": ft_status})
            return
    else:
        fine_tune_job_id = ""
        ft_job = {"trained_tokens": 0}

    adapter_id = f"{base_model.replace('/', '-')}-{method}"
    adapter_version = f"v{int(time.time())}"
    adapter = save_lora_adapter_version(
        adapter_id=adapter_id,
        version=adapter_version,
        base_model=base_model,
        checkpoint_uri=f"inline://adapters/{adapter_id}/{adapter_version}",
        metrics={
            "preference_alignment_score": float(preference_metrics["preference_alignment_score"]),
            "preference_pair_count": int(preference_metrics["pair_count"]),
            "chosen_avg": float(preference_metrics["chosen_avg"]),
            "rejected_avg": float(preference_metrics["rejected_avg"]),
            "trained_tokens": int(ft_job.get("trained_tokens") or 0),
        },
        provenance={
            "method": method,
            "dataset_version_id": dataset_version_id,
            "rlhf_dpo_job_id": job_id,
            "fine_tune_job_id": fine_tune_job_id,
        },
        tags=["rlhf", method],
        status="ready",
    )
    result = {
        "preference_alignment_score": float(preference_metrics["preference_alignment_score"]),
        "pair_count": int(preference_metrics["pair_count"]),
        "chosen_avg": float(preference_metrics["chosen_avg"]),
        "rejected_avg": float(preference_metrics["rejected_avg"]),
        "synthetic_negative_count": int(preference_metrics["synthetic_negative_count"]),
        "preference_rows": preference_metrics["rows"][:25],
        "method": method,
        "training_backend": training_backend,
        "telemetry_gates": telemetry_gates,
        "synthetic_negative_ratio": round(synthetic_ratio, 6),
        "fine_tune_job_id": fine_tune_job_id,
        "dataset_version_id": dataset_version_id,
        "adapter": adapter,
    }
    if native_training_result is not None:
        result["native_training"] = native_training_result
    update_rlhf_dpo_job(
        job_id,
        status="succeeded",
        result=result,
        error=None,
    )
    append_rlhf_dpo_job_event(job_id, "RLHF/DPO job completed", data=result)


@router.post("/finetune/experiments/rlhf-dpo/jobs")
async def create_rlhf_dpo_experiment_job(request: Request):
    from ..db import create_rlhf_dpo_job, get_ft_dataset_version

    body = await _read_json_body(request, "invalid JSON body")
    method = str(body.get("method") or "dpo").strip().lower()
    if method not in {"rlhf", "dpo"}:
        return _api_error("method must be 'rlhf' or 'dpo'", "validation_error", 422)

    base_model = str(body.get("base_model") or "nexus-prime-base").strip()
    dataset_version_id = str(body.get("dataset_version_id") or "").strip()
    if not dataset_version_id:
        return _api_error("dataset_version_id is required", "validation_error", 422)
    if get_ft_dataset_version(dataset_version_id) is None:
        return _api_error("dataset_version_id not found", "not_found", 404)

    config = body.get("config") if isinstance(body.get("config"), dict) else {}
    backend = str(config.get("training_backend") or "orchestration").strip().lower()
    if backend not in {"orchestration", "native"}:
        return _api_error("config.training_backend must be 'orchestration' or 'native'", "validation_error", 422)

    job = create_rlhf_dpo_job(
        method=method,
        base_model=base_model,
        dataset_version_id=dataset_version_id,
        config=config,
    )
    threading.Thread(target=_run_rlhf_dpo_job, args=(job["id"],), daemon=True).start()
    return {"job": job}


@router.get("/finetune/experiments/rlhf-dpo/jobs")
def list_rlhf_dpo_experiment_jobs(limit: int = 100):
    from ..db import list_rlhf_dpo_jobs

    rows = list_rlhf_dpo_jobs(limit=limit)
    return {"jobs": rows, "count": len(rows)}


@router.get("/finetune/experiments/rlhf-dpo/jobs/{job_id}")
def get_rlhf_dpo_experiment_job(job_id: str):
    from ..db import get_rlhf_dpo_job

    row = get_rlhf_dpo_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    return {"job": row}


@router.get("/finetune/experiments/rlhf-dpo/jobs/{job_id}/events")
def list_rlhf_dpo_experiment_job_events(job_id: str, limit: int = 200):
    from ..db import get_rlhf_dpo_job

    row = get_rlhf_dpo_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    events = row.get("events") if isinstance(row.get("events"), list) else []
    return {"job_id": job_id, "events": events[-max(1, int(limit)):], "count": len(events)}


@router.post("/finetune/experiments/rlhf-dpo/jobs/{job_id}/cancel")
def cancel_rlhf_dpo_experiment_job(job_id: str):
    from ..db import get_rlhf_dpo_job, update_rlhf_dpo_job

    row = get_rlhf_dpo_job(job_id)
    if row is None:
        return _api_error("job not found", "not_found", 404)
    if str(row.get("status") or "") not in {"succeeded", "failed", "cancelled"}:
        row = update_rlhf_dpo_job(job_id, status="cancelled", error={"message": "Cancelled by user"}) or row
    return {"job": row}
def _continual_policies_key() -> str:
    return "finetune.continual.policies.v1"


def _update_continual_policy(policy_id: str, updates: dict) -> dict | None:
    rows = _load_continual_policies()
    updated = None
    for idx, row in enumerate(rows):
        if str(row.get("id") or "") != str(policy_id):
            continue
        merged = dict(row)
        merged.update(dict(updates or {}))
        merged["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rows[idx] = merged
        updated = merged
        break
    if updated is not None:
        _save_continual_policies(rows)
    return updated


def _execute_continual_re_tune_task(payload: dict) -> str:
    from ..eval_pipeline import run_eval_suite

    policy_id = str(payload.get("policy_id") or "").strip()
    model = str(payload.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    threshold = float(payload.get("threshold") or 0.05)
    suites = payload.get("suites") if isinstance(payload.get("suites"), list) else ["code", "autonomy", "rag"]
    n_samples = max(2, min(int(payload.get("n_samples") or 8), 64))
    provider = str(payload.get("provider") or "ollama")
    include_trace = bool(payload.get("include_trace", True))

    batch = run_eval_suite(model=model, provider=provider, suites=suites, n_samples=n_samples)
    avg_score = float(batch.get("average_score") or 0.0)
    has_regression = bool(batch.get("has_regression"))

    current_policy = None
    if policy_id:
        for row in _load_continual_policies():
            if str(row.get("id") or "") == policy_id:
                current_policy = row
                break
    prev_score = float(current_policy.get("last_average_score") or 0.0) if current_policy else 0.0
    delta = avg_score - prev_score

    updates = {
        "last_run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "last_average_score": round(avg_score, 6),
        "last_delta": round(delta, 6),
        "run_count": int((current_policy or {}).get("run_count") or 0) + 1,
        "last_eval": {
            "suites": suites,
            "average_score": round(avg_score, 6),
            "has_regression": has_regression,
        },
    }
    if policy_id:
        _update_continual_policy(policy_id, updates)

    should_retune = (delta >= threshold) and (not has_regression)
    if not should_retune:
        return f"continual policy checked: avg={avg_score:.3f}, delta={delta:.3f}, threshold={threshold:.3f}, retune=no"

    rows = _training_rows_from_feedback(include_trace=include_trace, limit=5000)
    if not rows:
        return f"continual policy checked: avg={avg_score:.3f}, delta={delta:.3f}, retune_skipped=no_rows"

    try:
        bundle = _create_finetune_job_from_rows(
            model=model,
            rows=rows,
            source="continual_feedback_trace",
            provenance_extra={
                "policy_id": policy_id,
                "trigger_average_score": avg_score,
                "trigger_delta": delta,
                "include_trace": include_trace,
            },
        )
    except Exception as exc:
        err = str(exc)
        lowered = err.lower()
        transient_markers = ("cuda", "gpu", "out of memory", "nvidia", "resource", "capacity")
        if any(m in lowered for m in transient_markers):
            if policy_id:
                _update_continual_policy(
                    policy_id,
                    {
                        "last_trigger_error": err[:500],
                        "last_trigger_status": "deferred_capacity",
                    },
                )
            return (
                f"continual policy deferred: avg={avg_score:.3f}, delta={delta:.3f}, "
                f"reason={err[:160]}"
            )
        raise
    if policy_id:
        _update_continual_policy(
            policy_id,
            {
                "last_triggered_finetune_job_id": str(bundle.get("job", {}).get("id") or ""),
                "last_triggered_dataset_id": str(bundle.get("dataset_version", {}).get("dataset_id") or ""),
                "retune_count": int((current_policy or {}).get("retune_count") or 0) + 1,
                "last_trigger_status": "triggered",
            },
        )
    return (
        f"continual policy triggered: avg={avg_score:.3f}, delta={delta:.3f}, "
        f"fine_tune_job_id={bundle.get('job', {}).get('id', '')}"
    )


def _load_continual_policies() -> list[dict]:
    raw = db_load_pref(_continual_policies_key(), "[]")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_continual_policies(rows: list[dict]) -> None:
    db_save_pref(_continual_policies_key(), json.dumps(rows[-5000:]))


@router.post("/finetune/continual/schedule")
async def schedule_continual_finetune(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    model = str(body.get("model") or "nexus-prime-base").strip() or "nexus-prime-base"
    schedule = str(body.get("schedule") or "0 3 * * 0").strip()
    threshold = float(body.get("threshold") or 0.05)
    suites = body.get("suites") if isinstance(body.get("suites"), list) else ["code", "autonomy", "rag"]
    n_samples = max(2, min(int(body.get("n_samples") or 8), 64))
    provider = str(body.get("provider") or "ollama").strip() or "ollama"
    include_trace = bool(body.get("include_trace", True))

    policy_id = str(uuid.uuid4())[:8]

    task_payload = {
        "op": "continual_re_tune",
        "policy_id": policy_id,
        "model": model,
        "threshold": threshold,
        "suites": suites,
        "n_samples": n_samples,
        "provider": provider,
        "include_trace": include_trace,
        "mode": "benchmark_then_one_click",
    }
    task = f"__finetune_continual__:{json.dumps(task_payload, separators=(',', ':'))}"
    try:
        job = schedule_job(
            name=f"continual-retune:{model}",
            task=task,
            schedule=schedule,
            max_retries=int(body.get("max_retries", 1)),
            retry_backoff_secs=int(body.get("retry_backoff_secs", 300)),
        )
    except Exception as exc:
        return _api_error(str(exc), "validation_error", 422)

    row = {
        "id": policy_id,
        "scheduler_job_id": job["id"],
        "name": job["name"],
        "model": model,
        "schedule": schedule,
        "threshold": threshold,
        "suites": suites,
        "n_samples": n_samples,
        "provider": provider,
        "include_trace": include_trace,
        "run_count": 0,
        "retune_count": 0,
        "last_average_score": 0.0,
        "last_delta": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scaffold": False,
    }
    policies = _load_continual_policies()
    policies = [p for p in policies if str(p.get("id") or "") != policy_id]
    policies.append(row)
    _save_continual_policies(policies)
    return {"policy": row, "scheduler_job": job_to_dict(job)}


@router.get("/finetune/continual/schedule")
def list_continual_finetune_schedules():
    return {
        "policies": _load_continual_policies(),
        "scheduler_jobs": [
            job_to_dict(j)
            for j in list_jobs()
            if str(getattr(j, "name", "")).startswith("continual-retune:")
        ],
    }


@router.delete("/finetune/continual/schedule/{policy_id}")
def delete_continual_finetune_schedule(policy_id: str):
    rows = _load_continual_policies()
    target = None
    for row in rows:
        if str(row.get("id") or "") == policy_id:
            target = row
            break
    kept = [r for r in rows if str(r.get("id") or "") != policy_id]
    _save_continual_policies(kept)
    scheduler_job_id = str((target or {}).get("scheduler_job_id") or policy_id)
    cancelled = cancel_job(scheduler_job_id)
    return {"deleted": policy_id, "scheduler_job_id": scheduler_job_id, "scheduler_cancelled": bool(cancelled)}


@router.post("/finetune/continual/schedule/{policy_id}/run-now")
def run_continual_finetune_schedule_now(policy_id: str):
    rows = _load_continual_policies()
    target = None
    for row in rows:
        if str(row.get("id") or "") == policy_id:
            target = row
            break
    if target is None:
        return _api_error("policy not found", "not_found", 404)
    payload = {
        "op": "continual_re_tune",
        "policy_id": policy_id,
        "model": target.get("model"),
        "threshold": target.get("threshold"),
        "suites": target.get("suites"),
        "n_samples": target.get("n_samples"),
        "provider": target.get("provider"),
        "include_trace": target.get("include_trace", True),
    }
    summary = _execute_continual_re_tune_task(payload)
    return {"policy_id": policy_id, "summary": summary}
