import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app
from src.db import save_lora_adapter_version
from src.eval_pipeline import EvalTask


client = TestClient(app)


def _seed_adapter(adapter_id: str, version: str = "v1") -> None:
    save_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        base_model="nexus-prime-base",
        checkpoint_uri=f"inline://adapters/{adapter_id}/{version}",
        metrics={"loss": 0.12},
        provenance={"source": "pytest"},
    )


def _eval_task(suite: str, score: float) -> EvalTask:
    task = EvalTask(name=f"{suite}:nexus-prime-base", suite=suite, model="nexus-prime-base", provider="offline")
    task.score = score
    task.status = "completed"
    return task


def test_adapter_proof_report_persists_and_allows_promotion(monkeypatch):
    _seed_adapter("pytest-proof-adapter")

    def _fake_run_eval_suite(model: str, provider: str = "offline", suites=None, n_samples: int = 20, adapter_id=None):
        selected = list(suites or ["gsm8k", "arc"])
        score = 0.66 if adapter_id else 0.58
        jobs = [_eval_task(suite, score) for suite in selected]
        return {
            "model": model,
            "provider": provider,
            "adapter_id": adapter_id,
            "suites": selected,
            "jobs": jobs,
            "average_score": score,
            "regressions": 0,
            "has_regression": False,
        }

    monkeypatch.setattr("src.eval_pipeline.run_eval_suite", _fake_run_eval_suite)

    proof = client.post(
        "/finetune/adapters/pytest-proof-adapter/proof",
        json={"version": "v1", "suites": ["gsm8k", "arc"], "provider": "offline", "min_improvement": 0.01},
    )
    assert proof.status_code == 200
    report = proof.json()["proof_report"]
    assert report["passes"] is True
    assert report["promotion_gate"]["allowed"] is True
    assert report["improvement"] > 0

    promote = client.post(
        "/finetune/adapters/pytest-proof-adapter/promote",
        json={"version": "v1", "report_id": report["report_id"]},
    )
    assert promote.status_code == 200
    payload = promote.json()
    assert payload["promoted"] is True
    assert payload["adapter"]["status"] == "promoted"
    assert payload["adapter"]["promotion_report_id"] == report["report_id"]


def test_adapter_promotion_is_blocked_when_proof_fails(monkeypatch):
    _seed_adapter("pytest-proof-blocked")

    def _fake_run_eval_suite(model: str, provider: str = "offline", suites=None, n_samples: int = 20, adapter_id=None):
        selected = list(suites or ["gsm8k"])
        score = 0.40 if adapter_id else 0.58
        jobs = [_eval_task(suite, score) for suite in selected]
        return {
            "model": model,
            "provider": provider,
            "adapter_id": adapter_id,
            "suites": selected,
            "jobs": jobs,
            "average_score": score,
            "regressions": 0,
            "has_regression": False,
        }

    monkeypatch.setattr("src.eval_pipeline.run_eval_suite", _fake_run_eval_suite)

    proof = client.post(
        "/finetune/adapters/pytest-proof-blocked/proof",
        json={"version": "v1", "suites": ["gsm8k"], "provider": "offline", "min_improvement": 0.01},
    )
    assert proof.status_code == 200
    report = proof.json()["proof_report"]
    assert report["passes"] is False

    promote = client.post(
        "/finetune/adapters/pytest-proof-blocked/promote",
        json={"version": "v1", "report_id": report["report_id"]},
    )
    assert promote.status_code == 409
    assert promote.json()["type"] == "proof_gate_failed"