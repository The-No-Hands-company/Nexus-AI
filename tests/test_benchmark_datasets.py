"""tests/test_benchmark_datasets.py — Tests for dataset-backed benchmark runners and artifact export."""
from __future__ import annotations

import json
import sys
import unittest

sys.path.insert(0, ".")


# ── Dataset runner unit tests ─────────────────────────────────────────────────

class TestDatasetScoringHelpers(unittest.TestCase):
    def test_gsm8k_score_correct(self):
        from src.evals.dataset_runners import _score_gsm8k
        self.assertEqual(_score_gsm8k("72", "The answer is 72"), 1.0)

    def test_gsm8k_score_with_hash_format(self):
        from src.evals.dataset_runners import _score_gsm8k
        self.assertEqual(_score_gsm8k("72", "Let me calculate... #### 72"), 1.0)

    def test_gsm8k_score_wrong(self):
        from src.evals.dataset_runners import _score_gsm8k
        self.assertEqual(_score_gsm8k("72", "The answer is 99"), 0.0)

    def test_gsm8k_score_close_enough(self):
        from src.evals.dataset_runners import _score_gsm8k
        # Within 0.01 tolerance
        self.assertEqual(_score_gsm8k("10", "She earned $10.00"), 1.0)

    def test_truthfulqa_score_correct(self):
        from src.evals.dataset_runners import _score_truthfulqa
        score = _score_truthfulqa("Paris", "The capital of France is Paris.")
        self.assertGreater(score, 0.5)

    def test_truthfulqa_score_wrong(self):
        from src.evals.dataset_runners import _score_truthfulqa
        score = _score_truthfulqa("Paris", "London is the capital of France.")
        self.assertEqual(score, 0.0)

    def test_mmlu_score_correct_letter(self):
        from src.evals.dataset_runners import _score_mmlu
        self.assertEqual(_score_mmlu("C", "The answer is C"), 1.0)

    def test_mmlu_score_paren_format(self):
        from src.evals.dataset_runners import _score_mmlu
        self.assertEqual(_score_mmlu("B", "(B) Peace of Westphalia"), 1.0)

    def test_mmlu_score_wrong_letter(self):
        from src.evals.dataset_runners import _score_mmlu
        self.assertEqual(_score_mmlu("C", "The answer is A"), 0.0)

    def test_humaneval_score_with_function(self):
        from src.evals.dataset_runners import _score_humaneval_static, _HUMANEVAL_SAMPLES
        sample = _HUMANEVAL_SAMPLES[0]
        code = "    for idx, elem in enumerate(numbers):\n        for idx2, elem2 in enumerate(numbers):\n            if idx != idx2:\n                distance = abs(elem - elem2)\n                if distance < threshold:\n                    return True\n    return False"
        score = _score_humaneval_static(sample, code)
        self.assertGreater(score, 0.3)

    def test_humaneval_score_empty(self):
        from src.evals.dataset_runners import _score_humaneval_static, _HUMANEVAL_SAMPLES
        score = _score_humaneval_static(_HUMANEVAL_SAMPLES[0], "I don't know")
        self.assertLess(score, 0.3)

    def test_hellaswag_score_correct(self):
        from src.evals.dataset_runners import _score_hellaswag, _HELLASWAG_SAMPLES
        sample = _HELLASWAG_SAMPLES[0]
        correct_text = sample["endings"][int(sample["label"])]
        score = _score_hellaswag(sample["label"], sample["endings"], correct_text)
        self.assertGreater(score, 0.5)

    def test_extract_final_number(self):
        from src.evals.dataset_runners import _extract_final_number
        self.assertEqual(_extract_final_number("The answer is 42"), "42")
        self.assertEqual(_extract_final_number("#### 72"), "72")
        self.assertEqual(_extract_final_number("$10.00"), "10.00")
        self.assertIsNone(_extract_final_number("no numbers here"))


class TestDatasetSamples(unittest.TestCase):
    def test_gsm8k_samples_valid(self):
        from src.evals.dataset_runners import _GSM8K_SAMPLES
        self.assertGreaterEqual(len(_GSM8K_SAMPLES), 5)
        for s in _GSM8K_SAMPLES:
            self.assertIn("id", s)
            self.assertIn("question", s)
            self.assertIn("answer", s)

    def test_truthfulqa_samples_valid(self):
        from src.evals.dataset_runners import _TRUTHFULQA_SAMPLES
        self.assertGreaterEqual(len(_TRUTHFULQA_SAMPLES), 5)
        for s in _TRUTHFULQA_SAMPLES:
            self.assertIn("correct", s)
            self.assertIsInstance(s["incorrect"], list)

    def test_mmlu_samples_valid(self):
        from src.evals.dataset_runners import _MMLU_SAMPLES
        self.assertGreaterEqual(len(_MMLU_SAMPLES), 5)
        valid_letters = {"A", "B", "C", "D"}
        for s in _MMLU_SAMPLES:
            self.assertIn(s["answer"], valid_letters)
            self.assertEqual(len(s["choices"]), 4)

    def test_humaneval_samples_valid(self):
        from src.evals.dataset_runners import _HUMANEVAL_SAMPLES
        self.assertGreaterEqual(len(_HUMANEVAL_SAMPLES), 2)
        for s in _HUMANEVAL_SAMPLES:
            self.assertIn("entry_point", s)
            self.assertIn("prompt", s)
            self.assertIn("canonical_solution", s)

    def test_hellaswag_samples_valid(self):
        from src.evals.dataset_runners import _HELLASWAG_SAMPLES
        self.assertGreaterEqual(len(_HELLASWAG_SAMPLES), 2)
        for s in _HELLASWAG_SAMPLES:
            self.assertIn("endings", s)
            self.assertEqual(len(s["endings"]), 4)
            self.assertIn(s["label"], ["0", "1", "2", "3"])


class TestDatasetHash(unittest.TestCase):
    def test_hash_is_deterministic(self):
        from src.evals.dataset_runners import _hash_samples, _GSM8K_SAMPLES
        h1 = _hash_samples(_GSM8K_SAMPLES)
        h2 = _hash_samples(_GSM8K_SAMPLES)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_hash_changes_with_content(self):
        from src.evals.dataset_runners import _hash_samples
        h1 = _hash_samples([{"id": "a", "q": "1"}])
        h2 = _hash_samples([{"id": "b", "q": "2"}])
        self.assertNotEqual(h1, h2)


class TestPercentile(unittest.TestCase):
    def test_p50(self):
        from src.evals.dataset_runners import _percentile
        vals = [100.0, 200.0, 300.0, 400.0, 500.0]
        p50 = _percentile(vals, 50)
        self.assertGreater(p50, 0)
        self.assertLessEqual(p50, 500)

    def test_p95(self):
        from src.evals.dataset_runners import _percentile
        vals = list(range(1, 101, 1))
        vals = [float(v) for v in vals]
        p95 = _percentile(vals, 95)
        self.assertGreaterEqual(p95, 90)

    def test_empty(self):
        from src.evals.dataset_runners import _percentile
        self.assertEqual(_percentile([], 50), 0.0)


class TestDatasetRunnerImport(unittest.TestCase):
    def test_dataset_runners_dict(self):
        from src.evals.dataset_runners import DATASET_RUNNERS
        expected = {"gsm8k", "truthfulqa", "humaneval", "mmlu", "hellaswag"}
        self.assertEqual(set(DATASET_RUNNERS.keys()), expected)

    def test_all_runners_callable(self):
        from src.evals.dataset_runners import DATASET_RUNNERS
        for name, fn in DATASET_RUNNERS.items():
            self.assertTrue(callable(fn), f"{name} runner is not callable")

    def test_hf_disabled_by_default(self):
        import os
        # Default: HF disabled
        val = os.getenv("BENCHMARK_USE_HF_DATASETS", "false")
        self.assertNotEqual(val.lower(), "true")


class TestDatasetBenchmarkResultDataclass(unittest.TestCase):
    def test_summary_keys(self):
        from src.evals.dataset_runners import DatasetBenchmarkResult, SampleResult
        r = DatasetBenchmarkResult(
            run_id="test-001",
            dataset="gsm8k",
            dataset_version="inline-v1.0",
            split="test",
            model="gpt-4",
            provider="openai",
            num_samples=5,
            num_passed=4,
            accuracy=0.8,
            avg_latency_ms=123.0,
            p50_latency_ms=100.0,
            p95_latency_ms=200.0,
            created_at="2026-04-21T00:00:00Z",
            dataset_hash="abcdef123456",  # pragma: allowlist secret
        )
        summary = r.summary()
        self.assertEqual(summary["run_id"], "test-001")
        self.assertEqual(summary["accuracy"], 0.8)
        self.assertIn("dataset_hash", summary)
        self.assertIn("reproducibility_notes", summary)

    def test_to_dict_includes_samples(self):
        from src.evals.dataset_runners import DatasetBenchmarkResult, SampleResult
        s = SampleResult(sample_id="s1", prompt="Q", response="A", score=1.0, passed=True, latency_ms=50.0)
        r = DatasetBenchmarkResult(
            run_id="test-002", dataset="mmlu", dataset_version="inline-v1.0", split="test",
            model="gpt-4", provider="openai", num_samples=1, num_passed=1,
            accuracy=1.0, avg_latency_ms=50.0, p50_latency_ms=50.0, p95_latency_ms=50.0,
            created_at="2026-04-21T00:00:00Z", sample_results=[s],
        )
        d = r.to_dict()
        self.assertIn("sample_results", d)
        self.assertEqual(len(d["sample_results"]), 1)
        self.assertEqual(d["sample_results"][0]["sample_id"], "s1")


# ── Artifact export tests ─────────────────────────────────────────────────────

class TestJSONLExport(unittest.TestCase):
    def _make_run_data(self):
        return {
            "run_id": "test-001",
            "dataset": "gsm8k",
            "dataset_version": "inline-v1.0",
            "split": "test",
            "model": "gpt-4",
            "provider": "openai",
            "created_at": "2026-04-21T00:00:00Z",
            "accuracy": 0.8,
            "sample_results": [
                {"sample_id": "gsm8k_0001", "prompt": "Q1", "response": "A1", "score": 1.0, "passed": True, "latency_ms": 100.0},
                {"sample_id": "gsm8k_0002", "prompt": "Q2", "response": "A2", "score": 0.0, "passed": False, "latency_ms": 120.0},
            ],
        }

    def test_jsonl_has_one_line_per_sample(self):
        from src.evals.artifact_export import export_jsonl
        run = self._make_run_data()
        jsonl = export_jsonl(run)
        lines = [l for l in jsonl.strip().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_jsonl_lines_are_valid_json(self):
        from src.evals.artifact_export import export_jsonl
        run = self._make_run_data()
        jsonl = export_jsonl(run)
        for line in jsonl.strip().splitlines():
            obj = json.loads(line)
            self.assertIn("run_id", obj)
            self.assertIn("sample", obj)

    def test_jsonl_sample_has_metadata(self):
        from src.evals.artifact_export import export_jsonl
        run = self._make_run_data()
        jsonl = export_jsonl(run)
        first = json.loads(jsonl.splitlines()[0])
        self.assertEqual(first["dataset"], "gsm8k")
        self.assertEqual(first["sample"]["sample_id"], "gsm8k_0001")


class TestCSVExport(unittest.TestCase):
    def _make_run_data(self):
        return {
            "run_id": "test-csv-001",
            "dataset": "mmlu",
            "dataset_version": "inline-v1.0",
            "split": "test",
            "model": "gpt-4",
            "provider": "openai",
            "created_at": "2026-04-21T00:00:00Z",
            "accuracy": 0.9,
            "sample_results": [
                {"sample_id": "mmlu_0001", "prompt": "Q", "response": "C", "score": 1.0, "passed": True, "latency_ms": 80.0, "error": ""},
            ],
        }

    def test_csv_has_header(self):
        from src.evals.artifact_export import export_csv
        csv_str = export_csv(self._make_run_data())
        lines = csv_str.strip().splitlines()
        self.assertGreater(len(lines), 1)
        header = lines[0]
        self.assertIn("run_id", header)
        self.assertIn("dataset", header)
        self.assertIn("score", header)

    def test_csv_data_row_count(self):
        from src.evals.artifact_export import export_csv
        csv_str = export_csv(self._make_run_data())
        lines = csv_str.strip().splitlines()
        # 1 header + 1 data row
        self.assertEqual(len(lines), 2)

    def test_csv_is_parseable(self):
        import csv as csv_mod, io
        from src.evals.artifact_export import export_csv
        csv_str = export_csv(self._make_run_data())
        reader = csv_mod.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dataset"], "mmlu")


class TestHTMLExport(unittest.TestCase):
    def _make_run_data(self):
        return {
            "run_id": "test-html-001", "dataset": "gsm8k", "dataset_version": "inline-v1.0",
            "split": "test", "model": "gpt-4", "provider": "openai",
            "created_at": "2026-04-21T00:00:00Z", "accuracy": 0.8,
            "avg_latency_ms": 100.0, "p95_latency_ms": 150.0, "dataset_hash": "abc123",
            "sample_results": [
                {"sample_id": "s1", "prompt": "Q", "response": "A", "score": 1.0, "passed": True, "latency_ms": 100.0},
            ],
        }

    def test_html_is_valid_html(self):
        from src.evals.artifact_export import export_html_report
        html = export_html_report(run_data=self._make_run_data())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)

    def test_html_contains_accuracy(self):
        from src.evals.artifact_export import export_html_report
        html = export_html_report(run_data=self._make_run_data())
        self.assertIn("80.0%", html)

    def test_html_contains_model_info(self):
        from src.evals.artifact_export import export_html_report
        html = export_html_report(run_data=self._make_run_data())
        self.assertIn("gpt-4", html)
        self.assertIn("gsm8k", html)


class TestLeaderboardExport(unittest.TestCase):
    def test_leaderboard_schema(self):
        from src.evals.artifact_export import export_leaderboard_json
        results = [
            {"dataset": "gsm8k", "dataset_version": "inline-v1.0", "split": "test",
             "model": "gpt-4", "provider": "openai", "accuracy": 0.8,
             "num_samples": 10, "avg_latency_ms": 100.0, "p95_latency_ms": 150.0,
             "run_id": "test-001", "dataset_hash": "abc123", "created_at": "2026-04-21T00:00:00Z"},
        ]
        lb = export_leaderboard_json(results, suite_id="suite-001")
        self.assertEqual(lb["schema_version"], "1.0")
        self.assertEqual(lb["framework"], "nexus-ai")
        self.assertIsInstance(lb["entries"], list)
        self.assertEqual(len(lb["entries"]), 1)

    def test_leaderboard_entry_fields(self):
        from src.evals.artifact_export import export_leaderboard_json
        results = [
            {"dataset": "mmlu", "dataset_version": "v1", "split": "test",
             "model": "claude-3", "provider": "anthropic", "accuracy": 0.9,
             "num_samples": 10, "avg_latency_ms": 80.0, "p95_latency_ms": 120.0,
             "run_id": "test-002", "dataset_hash": "xyz789", "created_at": "2026-04-21T00:00:00Z"},
        ]
        entry = export_leaderboard_json(results)["entries"][0]
        self.assertEqual(entry["model_name"], "claude-3")
        self.assertEqual(entry["metric"], "accuracy")
        self.assertEqual(entry["value"], 0.9)
        self.assertIn("dataset_content_hash", entry)


class TestManifest(unittest.TestCase):
    def test_manifest_has_checksums(self):
        from src.evals.artifact_export import generate_manifest
        artifacts = {"jsonl": "line1\nline2", "csv": "col1,col2\nval1,val2"}
        manifest = generate_manifest(artifacts)
        self.assertIn("artifacts", manifest)
        self.assertIn("jsonl", manifest["artifacts"])
        self.assertIn("csv", manifest["artifacts"])
        self.assertIn("manifest_hash", manifest)

    def test_manifest_hashes_are_hex(self):
        from src.evals.artifact_export import generate_manifest
        manifest = generate_manifest({"data": "hello world"})
        checksum = manifest["artifacts"]["data"]
        self.assertEqual(len(checksum), 64)  # SHA-256 hex
        self.assertTrue(all(c in "0123456789abcdef" for c in checksum))

    def test_manifest_is_deterministic(self):
        from src.evals.artifact_export import generate_manifest
        m1 = generate_manifest({"a": "content"})
        m2 = generate_manifest({"a": "content"})
        self.assertEqual(m1["artifacts"]["a"], m2["artifacts"]["a"])


class TestSparkline(unittest.TestCase):
    def test_sparkline_length(self):
        from src.evals.artifact_export import _sparkline
        line = _sparkline([0.0, 0.5, 1.0, 0.8, 0.2], width=10)
        self.assertEqual(len(line), 10)

    def test_sparkline_empty(self):
        from src.evals.artifact_export import _sparkline
        line = _sparkline([], width=10)
        self.assertEqual(len(line), 10)


class TestUnifiedExport(unittest.TestCase):
    def _make_run_data(self):
        return {
            "run_id": "test-unified-001", "dataset": "gsm8k", "dataset_version": "inline-v1.0",
            "split": "test", "model": "gpt-4", "provider": "openai",
            "created_at": "2026-04-21T00:00:00Z", "accuracy": 0.7,
            "avg_latency_ms": 120.0, "p95_latency_ms": 200.0, "dataset_hash": "def456",
            "sample_results": [
                {"sample_id": "s1", "prompt": "Q", "response": "A", "score": 1.0, "passed": True, "latency_ms": 100.0},
                {"sample_id": "s2", "prompt": "Q", "response": "A", "score": 0.0, "passed": False, "latency_ms": 140.0},
            ],
        }

    def test_unified_all_formats(self):
        from src.evals.artifact_export import export_benchmark_artifacts
        result = export_benchmark_artifacts(run_data=self._make_run_data())
        self.assertIn("jsonl", result)
        self.assertIn("csv", result)
        self.assertIn("html", result)
        self.assertIn("leaderboard", result)
        self.assertIn("manifest", result)

    def test_unified_selected_formats(self):
        from src.evals.artifact_export import export_benchmark_artifacts
        result = export_benchmark_artifacts(run_data=self._make_run_data(), formats=["jsonl", "csv"])
        self.assertIn("jsonl", result)
        self.assertIn("csv", result)
        self.assertNotIn("html", result)

    def test_unified_manifest_covers_all_artifacts(self):
        from src.evals.artifact_export import export_benchmark_artifacts
        result = export_benchmark_artifacts(run_data=self._make_run_data(), formats=["jsonl", "csv", "manifest"])
        self.assertIn("manifest", result)
        manifest = result["manifest"]
        self.assertIn("jsonl", manifest["artifacts"])
        self.assertIn("csv", manifest["artifacts"])


# ── benchmark.py integration tests ────────────────────────────────────────────

class TestBenchmarkModuleDatasetFunctions(unittest.TestCase):
    def test_get_dataset_benchmark_history_empty(self):
        from src.benchmark import get_dataset_benchmark_history
        result = get_dataset_benchmark_history(dataset="gsm8k", limit=10)
        self.assertIn("results", result)
        self.assertIsInstance(result["results"], list)

    def test_export_benchmark_run_unknown(self):
        from src.benchmark import export_benchmark_run
        result = export_benchmark_run(run_id="nonexistent-run-id-xyz")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
