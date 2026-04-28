import unittest

from src.nexus_ai_contracts import build_systems_api_registration_payload


class TestNexusAIContractHelper(unittest.TestCase):
    def test_registration_payload_shape_is_stable(self):
        payload = build_systems_api_registration_payload("http://localhost:8000")

        self.assertEqual(payload["id"], "nexus-ai")
        self.assertEqual(payload["name"], "Nexus AI")
        self.assertEqual(payload["mode"], "orchestrated")
        self.assertTrue(payload["exposed"])
        self.assertEqual(payload["health"], "healthy")
        self.assertEqual(payload["upstreamUrl"], "http://localhost:8000")
        self.assertIn("model-routing", payload["capabilities"])
        self.assertIn("prompt-governance", payload["capabilities"])
        self.assertIn("safety-pipeline", payload["capabilities"])
        self.assertIn("rag", payload["capabilities"])
        self.assertIn("tool-execution", payload["capabilities"])
        self.assertTrue(payload["metadata"]["supportsModelRouting"])
        self.assertTrue(payload["metadata"]["supportsSafetyPipeline"])
        self.assertTrue(payload["metadata"]["supportsRAG"])

    def test_registration_payload_allows_custom_identity_and_health(self):
        payload = build_systems_api_registration_payload(
            upstream_url="https://ai.nexus.internal",
            tool_id="nexus-ai-node-b",
            tool_name="Nexus AI Node B",
            health="degraded",
        )

        self.assertEqual(payload["id"], "nexus-ai-node-b")
        self.assertEqual(payload["name"], "Nexus AI Node B")
        self.assertEqual(payload["upstreamUrl"], "https://ai.nexus.internal")
        self.assertEqual(payload["health"], "degraded")

    def test_capabilities_list_is_complete(self):
        payload = build_systems_api_registration_payload("http://localhost:8000")
        expected = [
            "model-routing",
            "prompt-governance",
            "safety-pipeline",
            "agent-orchestration",
            "ensemble-inference",
            "rag",
            "tool-execution",
            "observability",
        ]
        for cap in expected:
            self.assertIn(cap, payload["capabilities"], f"Missing capability: {cap}")


if __name__ == "__main__":
    unittest.main()
