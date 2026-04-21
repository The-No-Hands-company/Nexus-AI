"""tests/test_sdk_packaging.py — Tests for SDK packaging, compat validation, and operator."""
from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")


# ── Python SDK version ────────────────────────────────────────────────────────

class TestSDKVersion(unittest.TestCase):
    def test_version_importable(self):
        from sdk.python.nexus_ai_sdk._version import __version__, __api_version__, __min_server_version__
        self.assertIsInstance(__version__, str)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+")

    def test_api_version(self):
        from sdk.python.nexus_ai_sdk._version import __api_version__
        self.assertEqual(__api_version__, "v1")

    def test_min_server_version(self):
        from sdk.python.nexus_ai_sdk._version import __min_server_version__
        self.assertRegex(__min_server_version__, r"^\d+\.\d+\.\d+")


# ── SDK __init__ exports ──────────────────────────────────────────────────────

class TestSDKInit(unittest.TestCase):
    def test_top_level_exports(self):
        import sdk.python.nexus_ai_sdk as sdk_mod
        self.assertTrue(hasattr(sdk_mod, "NexusAIClient"))
        self.assertTrue(hasattr(sdk_mod, "NexusAIError"))
        self.assertTrue(hasattr(sdk_mod, "NexusOperator"))
        self.assertTrue(hasattr(sdk_mod, "OperatorConfig"))
        self.assertTrue(hasattr(sdk_mod, "RetryConfig"))
        self.assertTrue(hasattr(sdk_mod, "validate_compat"))
        self.assertTrue(hasattr(sdk_mod, "CompatReport"))
        self.assertTrue(hasattr(sdk_mod, "CompatibilityError"))

    def test_version_in_init(self):
        import sdk.python.nexus_ai_sdk as sdk_mod
        self.assertIsInstance(sdk_mod.__version__, str)

    def test_async_client_lazy_import(self):
        import sdk.python.nexus_ai_sdk as sdk_mod
        # Should not fail — lazy attribute
        AsyncCls = sdk_mod.AsyncNexusAIClient
        self.assertIsNotNone(AsyncCls)


# ── NexusAIClient unit tests ──────────────────────────────────────────────────

class TestNexusAIClient(unittest.TestCase):
    def _make_client(self):
        from sdk.python.nexus_ai_sdk.client import NexusAIClient
        return NexusAIClient(base_url="http://localhost:9999", api_key="test-key")  # pragma: allowlist secret

    def test_client_construction(self):
        client = self._make_client()
        self.assertEqual(client.base_url, "http://localhost:9999")
        self.assertEqual(client.api_key, "test-key")

    def test_headers_include_auth(self):
        client = self._make_client()
        headers = client._headers()
        self.assertIn("Authorization", headers)
        self.assertTrue(headers["Authorization"].startswith("Bearer "))

    def test_headers_no_key(self):
        from sdk.python.nexus_ai_sdk.client import NexusAIClient
        client = NexusAIClient(base_url="http://localhost:9999")
        headers = client._headers()
        self.assertNotIn("Authorization", headers)

    def test_nexus_error_has_status(self):
        from sdk.python.nexus_ai_sdk.client import NexusAIError
        err = NexusAIError("something failed", status=404)
        self.assertEqual(err.status, 404)
        self.assertIn("something failed", str(err))

    def test_stream_chunk_dataclass(self):
        from sdk.python.nexus_ai_sdk.client import StreamChunk
        chunk = StreamChunk(delta="hello", finish_reason="stop")
        self.assertEqual(chunk.delta, "hello")
        self.assertEqual(chunk.finish_reason, "stop")


# ── Operator tests ────────────────────────────────────────────────────────────

class TestNexusOperator(unittest.TestCase):
    def setUp(self):
        from sdk.python.nexus_ai_sdk.operator import NexusOperator
        NexusOperator.reset_default()

    def tearDown(self):
        from sdk.python.nexus_ai_sdk.operator import NexusOperator
        NexusOperator.reset_default()

    def test_operator_construction(self):
        from sdk.python.nexus_ai_sdk.operator import NexusOperator, OperatorConfig
        op = NexusOperator(OperatorConfig(base_url="http://localhost:9999", api_key="sk-test"))
        self.assertEqual(op.config.base_url, "http://localhost:9999")

    def test_default_singleton(self):
        import os
        from sdk.python.nexus_ai_sdk.operator import NexusOperator
        os.environ.setdefault("NEXUS_BASE_URL", "http://localhost:9999")
        op1 = NexusOperator.default()
        op2 = NexusOperator.default()
        self.assertIs(op1, op2)

    def test_reset_default(self):
        from sdk.python.nexus_ai_sdk.operator import NexusOperator
        import os
        os.environ.setdefault("NEXUS_BASE_URL", "http://localhost:9999")
        op1 = NexusOperator.default()
        NexusOperator.reset_default()
        op2 = NexusOperator.default()
        self.assertIsNot(op1, op2)

    def test_client_property(self):
        from sdk.python.nexus_ai_sdk.operator import NexusOperator, OperatorConfig
        from sdk.python.nexus_ai_sdk.client import NexusAIClient
        op = NexusOperator(OperatorConfig(base_url="http://localhost:9999"))
        self.assertIsInstance(op.client, NexusAIClient)

    def test_retry_config_defaults(self):
        from sdk.python.nexus_ai_sdk.operator import RetryConfig
        cfg = RetryConfig()
        self.assertEqual(cfg.max_attempts, 3)
        self.assertIn(503, cfg.retryable_status)
        self.assertIn(429, cfg.retryable_status)

    def test_retry_delay_is_bounded(self):
        from sdk.python.nexus_ai_sdk.operator import RetryConfig
        cfg = RetryConfig(base_delay_s=1.0, max_delay_s=5.0, jitter=0.0)
        for attempt in range(5):
            delay = cfg.delay(attempt)
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, 5.1)  # small epsilon for jitter

    def test_operator_with_retry_raises_non_retryable(self):
        """Non-retryable status (e.g. 400) should raise immediately without sleeping."""
        from sdk.python.nexus_ai_sdk.operator import NexusOperator, OperatorConfig
        from sdk.python.nexus_ai_sdk.client import NexusAIError
        op = NexusOperator(OperatorConfig(base_url="http://localhost:9999"))
        call_count = 0

        def bad_fn():
            nonlocal call_count
            call_count += 1
            raise NexusAIError("bad request", status=400)

        with self.assertRaises(NexusAIError):
            op._with_retry(bad_fn)
        self.assertEqual(call_count, 1)  # no retries for 400

    def test_operator_with_retry_retries_on_503(self):
        from sdk.python.nexus_ai_sdk.operator import NexusOperator, OperatorConfig, RetryConfig
        from sdk.python.nexus_ai_sdk.client import NexusAIError
        op = NexusOperator(OperatorConfig(
            base_url="http://localhost:9999",
            retry=RetryConfig(max_attempts=3, base_delay_s=0.0, jitter=0.0),
        ))
        call_count = 0
        responses = [NexusAIError("service unavailable", status=503),
                     NexusAIError("service unavailable", status=503),
                     None]

        def flaky_fn():
            nonlocal call_count
            r = responses[min(call_count, 2)]
            call_count += 1
            if r is not None:
                raise r
            return {"ok": True}

        result = op._with_retry(flaky_fn)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(call_count, 3)


# ── Compatibility validator tests ─────────────────────────────────────────────

class TestCompatValidator(unittest.TestCase):
    def test_validate_returns_report(self):
        from sdk.python.nexus_ai_sdk.compat import validate, CompatReport
        report = validate()
        self.assertIsInstance(report, CompatReport)

    def test_python_version_check_passes(self):
        from sdk.python.nexus_ai_sdk.compat import validate
        report = validate()
        python_check = next(c for c in report.checks if c.name == "python_version")
        self.assertTrue(python_check.passed, f"Python version check failed: {python_check.message}")

    def test_requests_dep_check(self):
        from sdk.python.nexus_ai_sdk.compat import validate
        report = validate()
        req_check = next((c for c in report.checks if c.name == "dep_requests"), None)
        self.assertIsNotNone(req_check)
        self.assertTrue(req_check.passed, f"requests check failed: {req_check.message}")

    def test_report_to_dict(self):
        from sdk.python.nexus_ai_sdk.compat import validate
        report = validate()
        d = report.to_dict()
        self.assertIn("sdk_version", d)
        self.assertIn("python_version", d)
        self.assertIn("checks", d)
        self.assertIn("passed", d)
        self.assertIn("errors", d)
        self.assertIn("warnings", d)

    def test_overall_passed(self):
        from sdk.python.nexus_ai_sdk.compat import validate
        report = validate()
        # In test environment, Python 3.9+ and requests are both present
        self.assertTrue(report.passed)

    def test_raise_if_failed_does_not_raise_when_ok(self):
        from sdk.python.nexus_ai_sdk.compat import validate
        report = validate()
        report.raise_if_failed()  # should not raise

    def test_assert_compatible_does_not_raise(self):
        from sdk.python.nexus_ai_sdk.compat import assert_compatible
        assert_compatible()  # no base_url, should pass

    def test_compat_error_is_runtime_error(self):
        from sdk.python.nexus_ai_sdk.compat import CompatibilityError
        self.assertTrue(issubclass(CompatibilityError, RuntimeError))

    def test_parse_version_helper(self):
        from sdk.python.nexus_ai_sdk.compat import _parse_version
        self.assertEqual(_parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(_parse_version("2.28.0"), (2, 28, 0))
        self.assertGreater(_parse_version("2.28.0"), _parse_version("2.27.99"))

    def test_optional_httpx_check(self):
        from sdk.python.nexus_ai_sdk.compat import validate
        report = validate()
        httpx_check = next((c for c in report.checks if c.name == "dep_httpx"), None)
        if httpx_check:
            # Optional — should not block overall pass even if missing
            if not httpx_check.passed:
                self.assertFalse(httpx_check.required)


# ── pyproject.toml structure test ─────────────────────────────────────────────

class TestPyprojectToml(unittest.TestCase):
    def test_pyproject_exists(self):
        import os
        path = "sdk/python/pyproject.toml"
        self.assertTrue(os.path.exists(path), f"{path} does not exist")

    def test_pyproject_has_required_fields(self):
        import os
        content = open("sdk/python/pyproject.toml").read()
        required = [
            "[project]",
            'name = "nexus-ai-sdk"',
            "requires-python",
            "dependencies",
            "[build-system]",
            "classifiers",
            "[project.urls]",
            "Changelog",
        ]
        for field in required:
            self.assertIn(field, content, f"pyproject.toml missing: {field}")

    def test_pyproject_python_versions_cover_39_to_313(self):
        content = open("sdk/python/pyproject.toml").read()
        for ver in ["3.9", "3.10", "3.11", "3.12", "3.13"]:
            self.assertIn(ver, content, f"Python {ver} not in classifiers")


# ── SDK README test ───────────────────────────────────────────────────────────

class TestSDKReadme(unittest.TestCase):
    def test_sdk_readme_exists(self):
        import os
        self.assertTrue(os.path.exists("sdk/README.md"))

    def test_sdk_readme_mentions_languages(self):
        content = open("sdk/README.md").read().lower()
        self.assertIn("python", content)


# ── TypeScript package.json test ──────────────────────────────────────────────

class TestTypescriptPackageJson(unittest.TestCase):
    def test_package_json_fields(self):
        import json as _json
        pkg = _json.load(open("sdk/typescript/package.json"))
        self.assertEqual(pkg["name"], "@nexus-ai/sdk")
        self.assertIn("version", pkg)
        self.assertIn("exports", pkg)
        self.assertIn("scripts", pkg)
        self.assertIn("engines", pkg)

    def test_package_json_exports_main(self):
        import json as _json
        pkg = _json.load(open("sdk/typescript/package.json"))
        exports = pkg.get("exports", {})
        self.assertIn(".", exports)

    def test_package_json_has_prepublish(self):
        import json as _json
        pkg = _json.load(open("sdk/typescript/package.json"))
        scripts = pkg.get("scripts", {})
        self.assertIn("prepublishOnly", scripts)

    def test_tsconfig_exists(self):
        import os
        self.assertTrue(os.path.exists("sdk/typescript/tsconfig.json"))

    def test_tsconfig_strict(self):
        import json as _json
        cfg = _json.load(open("sdk/typescript/tsconfig.json"))
        self.assertTrue(cfg["compilerOptions"]["strict"])
        self.assertIn("outDir", cfg["compilerOptions"])
        self.assertIn("declaration", cfg["compilerOptions"])


# ── Go module test ────────────────────────────────────────────────────────────

class TestGoSDK(unittest.TestCase):
    def test_go_mod_exists(self):
        import os
        self.assertTrue(os.path.exists("sdk/go/go.mod"))

    def test_operator_go_exists(self):
        import os
        self.assertTrue(os.path.exists("sdk/go/nexusai/operator.go"))

    def test_go_operator_has_required_symbols(self):
        content = open("sdk/go/nexusai/operator.go").read()
        for symbol in ["NexusOperator", "Operator", "BenchmarkDataset", "IsHealthy", "CompatibilityReport", "SDKVersion"]:
            self.assertIn(symbol, content, f"Missing symbol: {symbol}")

    def test_go_client_has_dataset_methods(self):
        content = open("sdk/go/nexusai/client.go").read()
        for method in ["BenchmarkDataset", "BenchmarkDatasetSuite", "BenchmarkExport", "BenchmarkDatasetHistory"]:
            self.assertIn(method, content, f"Missing method: {method}")


# ── Async client smoke test ───────────────────────────────────────────────────

class TestAsyncClientStructure(unittest.TestCase):
    def test_async_client_importable(self):
        from sdk.python.nexus_ai_sdk.async_client import AsyncNexusAIClient
        self.assertIsNotNone(AsyncNexusAIClient)

    def test_async_client_has_methods(self):
        from sdk.python.nexus_ai_sdk.async_client import AsyncNexusAIClient
        for method in ["chat_completions", "chat_stream", "run_agent", "stream_agent",
                        "benchmark_dataset", "benchmark_dataset_suite", "benchmark_export",
                        "health", "close"]:
            self.assertTrue(hasattr(AsyncNexusAIClient, method), f"Missing method: {method}")

    def test_async_client_context_manager_methods(self):
        from sdk.python.nexus_ai_sdk.async_client import AsyncNexusAIClient
        self.assertTrue(hasattr(AsyncNexusAIClient, "__aenter__"))
        self.assertTrue(hasattr(AsyncNexusAIClient, "__aexit__"))


if __name__ == "__main__":
    unittest.main()
