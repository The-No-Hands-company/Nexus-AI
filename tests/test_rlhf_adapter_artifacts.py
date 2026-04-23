import sys
import time
import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app
from src.db import compare_lora_adapter_versions, save_ft_dataset_version, save_lora_adapter_version


client = TestClient(app)


def _wait_for_rlhf_job(job_id: str, timeout: float = 10.0) -> dict:
    started = time.time()
    while time.time() - started <= timeout:
        payload = client.get(f"/finetune/experiments/rlhf-dpo/jobs/{job_id}")
        assert payload.status_code == 200
        job = payload.json()["job"]
        if job.get("status") in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for RLHF/DPO job {job_id}")


def test_rlhf_dpo_uses_dataset_backed_preference_metrics():
    dataset = save_ft_dataset_version(
        dataset_id="pytest-rlhf-dataset",
        source="pytest",
        fmt="jsonl",
        row_count=2,
        provenance={"source": "pytest"},
        checksum="pytest-checksum",
        preview_rows=[
            {
                "prompt": "Explain why Redis helps with sessions.",
                "chosen": "Redis provides fast shared state for session storage across workers.",
                "rejected": "Sessions are unrelated to Redis.",
            },
            {
                "prompt": "What does DPO optimize?",
                "response": "DPO optimizes a model using preference comparisons between outputs.",
            },
        ],
    )
    assert dataset["preview_rows"]

    created = client.post(
        "/finetune/experiments/rlhf-dpo/jobs",
        json={
            "method": "dpo",
            "base_model": "nexus-prime-base",
            "dataset_version_id": dataset["dataset_id"],
            "config": {"beta": 0.1},
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job"]["id"]

    job = _wait_for_rlhf_job(job_id)
    assert job["status"] == "succeeded"
    result = job["result"]
    assert result["pair_count"] == 2
    assert result["preference_alignment_score"] > 0
    assert result["chosen_avg"] > result["rejected_avg"]
    assert result["synthetic_negative_count"] == 1
    assert result["preference_rows"]
    assert all("margin" in row for row in result["preference_rows"])

    adapter_metrics = result["adapter"]["metrics"]
    assert adapter_metrics["preference_pair_count"] == 2
    assert adapter_metrics["preference_alignment_score"] == result["preference_alignment_score"]


def test_rlhf_dpo_fails_when_dataset_has_no_usable_rows():
    dataset = save_ft_dataset_version(
        dataset_id="pytest-empty-rlhf-dataset",
        source="pytest",
        fmt="jsonl",
        row_count=1,
        provenance={"source": "pytest"},
        checksum="pytest-empty-checksum",
        preview_rows=[{"note": "missing prompt and response"}],
    )

    created = client.post(
        "/finetune/experiments/rlhf-dpo/jobs",
        json={
            "method": "rlhf",
            "base_model": "nexus-prime-base",
            "dataset_version_id": dataset["dataset_id"],
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job"]["id"]

    job = _wait_for_rlhf_job(job_id)
    assert job["status"] == "failed"
    assert "usable preference rows" in str(job["error"]["message"])


def test_compare_lora_adapter_versions_reports_artifact_delta(tmp_path: Path):
    left_dir = tmp_path / "adapter-v1"
    right_dir = tmp_path / "adapter-v2"
    left_dir.mkdir()
    right_dir.mkdir()
    (left_dir / "adapter.bin").write_text("left-version", encoding="utf-8")
    (right_dir / "adapter.bin").write_text("right-version", encoding="utf-8")
    (right_dir / "adapter.safetensors").write_text("weights", encoding="utf-8")

    save_lora_adapter_version(
        adapter_id="pytest-artifact-adapter",
        version="v1",
        base_model="nexus-prime-base",
        checkpoint_uri=left_dir.as_posix(),
        metrics={"loss": 1.0},
    )
    save_lora_adapter_version(
        adapter_id="pytest-artifact-adapter",
        version="v2",
        base_model="nexus-prime-base",
        checkpoint_uri=right_dir.as_posix(),
        metrics={"loss": 0.7},
    )

    comparison = compare_lora_adapter_versions("pytest-artifact-adapter", "v1", "v2")
    assert comparison is not None
    assert comparison["metric_delta"]["loss"] == -0.3
    artifact_delta = comparison["artifact_delta"]
    assert artifact_delta["left"]["exists"] is True
    assert artifact_delta["right"]["exists"] is True
    assert artifact_delta["left"]["kind"] == "directory"
    assert artifact_delta["right"]["file_count"] == 2
    assert artifact_delta["same_artifact"] is False
    assert artifact_delta["file_count_delta"] == 1
    assert artifact_delta["right"]["sha256"]


def test_save_lora_adapter_version_materializes_local_artifact(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ADAPTER_STORE_DIR", tmp_path.as_posix())
    saved = save_lora_adapter_version(
        adapter_id="pytest-inline-adapter",
        version="v1",
        base_model="nexus-prime-base",
        checkpoint_uri="inline://adapters/pytest-inline-adapter/v1",
        metrics={"quality": 0.88},
        provenance={"source": "pytest"},
    )
    artifact_uri = str(saved.get("artifact_uri") or "")
    assert artifact_uri
    artifact_dir = Path(artifact_uri)
    assert artifact_dir.exists()
    manifest_path = artifact_dir / "manifest.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["adapter_id"] == "pytest-inline-adapter"
    assert payload["version"] == "v1"
    assert payload["source_checkpoint_uri"].startswith("inline://")
    assert payload["manifest_sha256"]
