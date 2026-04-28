import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.feature_flags import ENABLE_CREATIVE_TOOLS, ENABLE_FEDERATED_LLM
from src.creative_jobs import create_creative_job, get_creative_job_status
from src.db import run_eval_creative_retention_cleanup
from src.eval_pipeline import generate_model_card, list_eval_jobs, run_eval_suite, run_regression_benchmark
from src.feature_flags import set_flag
from src.federated import (
    compute_and_submit_update,
    get_fallback_hook_summary,
    get_federation_status,
    list_fallback_hooks,
    try_federated_inference,
)


class TestPhaseRoadmapPaths(unittest.TestCase):
    def setUp(self) -> None:
        set_flag(ENABLE_FEDERATED_LLM, False)
        set_flag(ENABLE_CREATIVE_TOOLS, False)

    def test_federated_toggle_and_fallback_hooks(self):
        disabled = try_federated_inference(messages=[{"role": "user", "content": "hi"}], task="hello")
        self.assertFalse(disabled.get("ok"))
        self.assertEqual(disabled.get("reason"), "disabled")

        set_flag(ENABLE_FEDERATED_LLM, True)
        no_endpoint = try_federated_inference(messages=[{"role": "user", "content": "hi"}], task="hello")
        self.assertFalse(no_endpoint.get("ok"))
        self.assertIn(no_endpoint.get("reason"), {"missing_endpoint", "request_failed"})

        result = compute_and_submit_update(samples=[{"x": 1}], global_round=1)
        payload = result.to_dict()
        self.assertEqual(payload["status"], "submitted")
        self.assertTrue(payload["submitted"])

        status = get_federation_status()
        self.assertTrue(status.get("enabled"))
        self.assertGreaterEqual(int(status.get("total_rounds") or 0), 1)
        summary = get_fallback_hook_summary(limit=50)
        self.assertGreaterEqual(int(summary.get("count") or 0), 1)
        self.assertIsInstance(summary.get("reason_counts"), dict)
        hooks = list_fallback_hooks(limit=20)
        self.assertGreaterEqual(len(hooks), 1)

    def test_creative_async_jobs_contract(self):
        disabled = create_creative_job(kind="music", prompt="warm synth pads", params={"duration": 12})
        self.assertFalse(disabled.get("ok"))
        self.assertEqual(disabled.get("error"), "creative_tools_disabled")

        set_flag(ENABLE_CREATIVE_TOOLS, True)
        created = create_creative_job(kind="music", prompt="warm synth pads", params={"duration": 12})
        self.assertTrue(created.get("ok"))
        self.assertEqual(created.get("status"), "queued")
        self.assertTrue(created.get("job_id"))

        time.sleep(0.2)
        polled = get_creative_job_status(created["job_id"])
        self.assertIsNotNone(polled)
        self.assertEqual(polled.get("status"), "completed")
        self.assertTrue(polled.get("result", {}).get("ok"))
        artifact = polled.get("artifact") or {}
        self.assertIn("mime", artifact)
        self.assertIn("uri", artifact)
        self.assertIn("safety_tags", artifact)
        self.assertIsInstance(artifact.get("safety_tags"), list)

    def test_eval_jobs_persist_and_feed_model_card(self):
        model = "nexus-eval-test-model"
        batch = run_eval_suite(model=model, provider="offline", suites=["code", "safety"], n_samples=5)
        self.assertEqual(batch.get("model"), model)
        self.assertEqual(len(batch.get("results", [])), 2)

        regression = run_regression_benchmark(model=model, provider="offline", suites=["code"], n_samples=3)
        self.assertIn("suite_results", regression)
        self.assertGreaterEqual(len(regression.get("suite_results", [])), 1)

        jobs = [j for j in list_eval_jobs() if str(getattr(j, "model", "")) == model]
        self.assertGreaterEqual(len(jobs), 2)

        card = generate_model_card(model=model)
        self.assertIn("# Model Card:", card)
        self.assertIn("Evaluations", card)

        cleanup = run_eval_creative_retention_cleanup(eval_retention_days=365, creative_retention_days=365, max_rows=5000)
        self.assertTrue(cleanup.get("ok"))
        self.assertIn("eval_jobs", cleanup)
        self.assertIn("creative_jobs", cleanup)


if __name__ == "__main__":
    unittest.main()
