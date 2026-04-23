import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app
from src.db import save_lora_adapter_version


client = TestClient(app)


def _seed_adapter(adapter_id: str, version: str = "v1") -> None:
    save_lora_adapter_version(
        adapter_id=adapter_id,
        version=version,
        base_model="nexus-prime-base",
        checkpoint_uri=f"inline://adapters/{adapter_id}/{version}",
        metrics={"loss": 0.2},
        provenance={"source": "pytest"},
    )


def test_hot_swap_blocks_when_regression_gate_fails(monkeypatch):
    _seed_adapter("pytest-gate-block-adapter")

    def _regression_fail(**kwargs):
        return {
            "model": kwargs.get("model", "nexus-prime-base"),
            "provider": kwargs.get("provider", "ollama"),
            "threshold": kwargs.get("threshold", 0.05),
            "suite_results": [{"suite": "gsm8k", "score": 0.3, "baseline": 0.6, "delta": -0.3, "regression": True}],
            "regression_count": 1,
            "ok": False,
        }

    monkeypatch.setattr("src.eval_pipeline.run_regression_benchmark", _regression_fail)

    response = client.post(
        "/finetune/adapters/pytest-gate-block-adapter/hot-swap",
        json={"version": "v1", "target_model": "nexus-prime-base"},
    )
    assert response.status_code == 409
    payload = response.json()
    assert payload["type"] == "regression_gate_failed"
    assert "regression gate blocked" in payload["error"]


def test_hot_swap_succeeds_when_regression_gate_passes(monkeypatch):
    _seed_adapter("pytest-gate-pass-adapter")

    def _regression_ok(**kwargs):
        return {
            "model": kwargs.get("model", "nexus-prime-base"),
            "provider": kwargs.get("provider", "ollama"),
            "threshold": kwargs.get("threshold", 0.05),
            "suite_results": [{"suite": "gsm8k", "score": 0.72, "baseline": 0.7, "delta": 0.02, "regression": False}],
            "regression_count": 0,
            "ok": True,
        }

    monkeypatch.setattr("src.eval_pipeline.run_regression_benchmark", _regression_ok)

    response = client.post(
        "/finetune/adapters/pytest-gate-pass-adapter/hot-swap",
        json={"version": "v1", "target_model": "nexus-prime-base"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["swapped"] is True
    assert payload["regression_gate"]["allowed"] is True
    assert payload["regression_gate"]["regression_count"] == 0


def test_nexus_prime_alpha_wiring_honors_regression_gate(monkeypatch):
    def _regression_fail(**kwargs):
        return {
            "model": kwargs.get("model", "nexus-prime-alpha"),
            "provider": kwargs.get("provider", "ollama"),
            "threshold": kwargs.get("threshold", 0.05),
            "suite_results": [{"suite": "arc", "score": 0.2, "baseline": 0.5, "delta": -0.3, "regression": True}],
            "regression_count": 1,
            "ok": False,
        }

    monkeypatch.setattr("src.eval_pipeline.run_regression_benchmark", _regression_fail)

    blocked = client.post(
        "/finetune/personas/nexus-prime-alpha/wire",
        json={"model": "nexus-prime-alpha", "provider_order": ["ollama"]},
    )
    assert blocked.status_code == 409

    def _regression_ok(**kwargs):
        return {
            "model": kwargs.get("model", "nexus-prime-alpha"),
            "provider": kwargs.get("provider", "ollama"),
            "threshold": kwargs.get("threshold", 0.05),
            "suite_results": [{"suite": "arc", "score": 0.65, "baseline": 0.63, "delta": 0.02, "regression": False}],
            "regression_count": 0,
            "ok": True,
        }

    monkeypatch.setattr("src.eval_pipeline.run_regression_benchmark", _regression_ok)

    allowed = client.post(
        "/finetune/personas/nexus-prime-alpha/wire",
        json={"model": "nexus-prime-alpha", "provider_order": ["ollama"]},
    )
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["wired"] is True
    assert payload["wiring"]["regression_gate"]["allowed"] is True
