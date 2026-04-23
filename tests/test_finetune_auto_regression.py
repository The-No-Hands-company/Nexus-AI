import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.routes import _run_fine_tuning_job
from src.api.schemas import FineTuningJob
from src.db import (
    create_fine_tuning_job,
    create_fine_tuning_job_event,
    get_fine_tuning_job,
    list_fine_tuning_job_events,
)


def test_fine_tune_job_runs_post_train_regression(monkeypatch):
    called = {"count": 0}

    def _fake_regression_benchmark(model: str, provider: str, suites: list[str], threshold: float, n_samples: int):
        called["count"] += 1
        assert model == "nexus-prime-base"
        assert provider == "offline"
        assert suites == ["gsm8k", "arc", "safety"]
        return {"overall_regression": False, "current_avg": 0.81}

    monkeypatch.setattr("src.eval_pipeline.run_regression_benchmark", _fake_regression_benchmark)

    job = FineTuningJob(
        model="nexus-prime-base",
        training_file="file-nonexistent",
        validation_file=None,
        hyperparameters={},
        status="queued",
    ).model_dump()
    assert create_fine_tuning_job(job)
    create_fine_tuning_job_event(job["id"], "Job created", data={"status": "queued"})

    _run_fine_tuning_job(job["id"])

    stored = get_fine_tuning_job(job["id"])
    assert stored is not None
    assert stored["status"] == "succeeded"
    assert called["count"] == 1

    events = list_fine_tuning_job_events(job["id"], limit=50)
    messages = [str(evt.get("message") or "") for evt in events]
    assert any("Post-train regression benchmark completed" in message for message in messages)
