from __future__ import annotations

"""Async creative job contracts (music + 3D) behind feature flags."""

import time
import uuid
from typing import Any

from .config.feature_flags import ENABLE_CREATIVE_TOOLS
from .db import get_creative_job, list_creative_jobs, save_creative_job
from .feature_flags import is_enabled
from .tools.music_tools import generate_music


def _now() -> float:
    return time.time()


def _normalize_kind(kind: str) -> str:
    value = str(kind or "").strip().lower()
    if value in {"music", "audio", "song"}:
        return "music"
    if value in {"3d", "model", "mesh"}:
        return "3d"
    return ""


def _artifact_metadata(kind: str, job_id: str, status: str, ext_hint: str = "") -> dict[str, Any]:
    normalized_kind = _normalize_kind(kind)
    if normalized_kind == "music":
        mime = "audio/wav"
        ext = "wav"
    else:
        fmt = str(ext_hint or "glb").strip().lower() or "glb"
        ext = fmt
        mime = "model/gltf-binary" if fmt == "glb" else "model/obj" if fmt == "obj" else "application/octet-stream"
    uri = f"/artifacts/creative/{job_id}.{ext}"
    return {
        "mime": mime,
        "uri": uri,
        "safety_tags": ["unreviewed", "stub_generated"] if status != "failed" else ["unreviewed", "generation_failed"],
    }


def create_creative_job(kind: str, prompt: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not is_enabled(ENABLE_CREATIVE_TOOLS, default=False):
        return {
            "ok": False,
            "error": "creative_tools_disabled",
            "message": "Creative tools are disabled. Enable ENABLE_CREATIVE_TOOLS first.",
        }

    normalized_kind = _normalize_kind(kind)
    if not normalized_kind:
        return {
            "ok": False,
            "error": "unsupported_kind",
            "message": "kind must be one of: music, 3d",
        }

    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        return {
            "ok": False,
            "error": "invalid_prompt",
            "message": "prompt is required",
        }

    payload = dict(params or {})
    created_at = _now()
    job = {
        "job_id": f"creative_{normalized_kind}_{uuid.uuid4().hex[:12]}",
        "kind": normalized_kind,
        "prompt": clean_prompt,
        "params": payload,
        "status": "queued",
        "created_at": created_at,
        "updated_at": created_at,
        "eta_seconds": 1,
        "backend": "stub",
        "result": None,
        "error": None,
        "artifact": _artifact_metadata(
            normalized_kind,
            f"creative_{normalized_kind}_{uuid.uuid4().hex[:12]}",
            "queued",
            ext_hint=str(payload.get("format") or "glb"),
        ),
    }
    job["artifact"] = _artifact_metadata(
        normalized_kind,
        str(job.get("job_id") or ""),
        "queued",
        ext_hint=str(payload.get("format") or "glb"),
    )
    saved = save_creative_job(job)
    saved["ok"] = True
    return saved


def _complete_stub_job(job: dict[str, Any]) -> dict[str, Any]:
    kind = _normalize_kind(str(job.get("kind") or ""))
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    prompt = str(job.get("prompt") or "")

    if kind == "music":
        result = generate_music(
            prompt=prompt,
            duration=int(params.get("duration") or 15),
            style=str(params.get("style") or "ambient"),
        )
        result["artifact"] = _artifact_metadata("music", str(job.get("job_id") or ""), "completed", ext_hint="wav")
    else:
        result = {
            "ok": True,
            "job_id": f"model3d_{uuid.uuid4().hex[:12]}",
            "backend": "stub",
            "model": "placeholder",
            "prompt": prompt,
            "format": str(params.get("format") or "glb"),
            "status": "queued",
            "created_at": _now(),
        }
        result["artifact"] = _artifact_metadata(
            "3d",
            str(job.get("job_id") or ""),
            "completed",
            ext_hint=str(params.get("format") or "glb"),
        )

    completed = dict(job)
    completed["updated_at"] = _now()
    if bool(result.get("ok", False)):
        completed["status"] = "completed"
        completed["result"] = result
        completed["error"] = None
        completed["artifact"] = dict(result.get("artifact") or _artifact_metadata(kind, str(job.get("job_id") or ""), "completed", ext_hint=str(params.get("format") or "glb")))
    else:
        completed["status"] = "failed"
        completed["result"] = None
        completed["error"] = {
            "code": str(result.get("error") or "creative_job_failed"),
            "message": str(result.get("message") or "Creative job failed"),
        }
        completed["artifact"] = _artifact_metadata(kind, str(job.get("job_id") or ""), "failed", ext_hint=str(params.get("format") or "glb"))
    save_creative_job(completed)
    completed["ok"] = True
    return completed


def get_creative_job_status(job_id: str) -> dict[str, Any] | None:
    row = get_creative_job(job_id)
    if not row:
        return None
    status = str(row.get("status") or "queued")
    age = _now() - float(row.get("created_at") or _now())
    if status == "queued" and age >= 0.15:
        row = _complete_stub_job(row)
    row["ok"] = True
    return row


def list_creative_jobs_status(kind: str = "", limit: int = 50) -> list[dict[str, Any]]:
    rows = list_creative_jobs(kind=_normalize_kind(kind), limit=max(1, min(int(limit or 50), 500)))
    hydrated = []
    for row in rows:
        job_id = str(row.get("job_id") or "")
        hydrated_row = get_creative_job_status(job_id) if job_id else row
        if hydrated_row:
            hydrated.append(hydrated_row)
    return hydrated
