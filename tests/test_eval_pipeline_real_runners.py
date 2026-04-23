import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import eval_pipeline


def test_suite_probe_score_uses_task_rows_not_hash_seed():
    score, rows = eval_pipeline._suite_probe_score("gsm8k", "model-a", "openai")
    assert isinstance(score, float)
    assert rows
    assert rows[0]["task_id"]
    assert "source" in rows[0]


def test_create_eval_job_humaneval_produces_grounded_results():
    job = eval_pipeline.create_eval_job(
        suite="humaneval",
        model="nexus-ai/auto",
        provider="openai",
        n_samples=3,
    )
    assert job.status == "completed"
    assert len(job.results) == 3
    assert all("response" in row for row in job.results)
    assert all("score" in row for row in job.results)


def test_run_eval_suite_keeps_requested_suites_and_scores():
    batch = eval_pipeline.run_eval_suite(
        model="nexus-ai/auto",
        provider="openai",
        suites=["advglue", "multilingual", "gsm8k"],
        n_samples=2,
    )
    assert batch["suites"] == ["advglue", "multilingual", "gsm8k"]
    assert len(batch["jobs"]) == 3
    assert 0.0 <= batch["average_score"] <= 1.0


def test_regression_benchmark_sets_baseline_when_missing():
    unique_model = "nexus-ai/test-real-runner"
    result = eval_pipeline.run_regression_benchmark(
        model=unique_model,
        provider="openai",
        suites=["arc"],
        threshold=0.05,
        n_samples=2,
    )
    assert result["ok"] is True
    assert result["suite_results"][0]["baseline"] is not None
