import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app import app


client = TestClient(app)


class TestExternalChannelsAndMcp(unittest.TestCase):
    def test_slack_url_verification_challenge(self):
        response = client.post(
            "/integrations/slack/events",
            json={"type": "url_verification", "challenge": "abc123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("challenge"), "abc123")

    def test_discord_inbound_secret_enforced(self):
        with patch.dict("os.environ", {"DISCORD_INBOUND_SECRET": "topsecret"}, clear=False):  # pragma: allowlist secret
            bad = client.post(
                "/integrations/discord/messages",
                json={"content": "hello", "channel_id": "123"},
            )
            self.assertEqual(bad.status_code, 403)

            ok = client.post(
                "/integrations/discord/messages",
                headers={"x-discord-secret": "topsecret"},  # pragma: allowlist secret
                json={"content": "hello", "channel_id": "123"},
            )
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(ok.json().get("accepted"))
            self.assertTrue(ok.json().get("run_id"))

    def test_github_signature_enforced(self):
        with patch.dict("os.environ", {"GITHUB_WEBHOOK_SECRET": "secret"}, clear=False):  # pragma: allowlist secret
            resp = client.post(
                "/integrations/github-actions/event",
                headers={"x-github-event": "push"},
                json={"repository": {"full_name": "acme/repo"}, "ref": "refs/heads/main"},
            )
            self.assertEqual(resp.status_code, 403)

    def test_mcp_client_list_empty_by_default(self):
        with patch.dict("os.environ", {"MCP_TOOLS": ""}, clear=False):
            resp = client.get("/mcp/tools")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json().get("count"), 0)

    def test_mcp_server_tools_list_and_call(self):
        with patch.dict(
            "os.environ",
            {
                "MCP_SERVER_MODE": "true",
                "MCP_SERVER_ALLOWED_TOOLS": "calculate,json_format",
            },
            clear=False,
        ):
            list_resp = client.post(
                "/mcp/server",
                json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}},
            )
            self.assertEqual(list_resp.status_code, 200)
            tool_names = {t.get("name") for t in list_resp.json().get("result", {}).get("tools", [])}
            self.assertIn("calculate", tool_names)
            self.assertNotIn("run_command", tool_names)

            call_resp = client.post(
                "/mcp/server",
                json={
                    "jsonrpc": "2.0",
                    "id": "2",
                    "method": "tools/call",
                    "params": {"name": "calculate", "arguments": {"expr": "1+1"}},
                },
            )
            self.assertEqual(call_resp.status_code, 200)
            text_payload = call_resp.json().get("result", {}).get("content", [{}])[0].get("text", "")
            self.assertIn("2", text_payload)

    def test_mcp_server_rejects_disallowed_tool(self):
        with patch.dict(
            "os.environ",
            {
                "MCP_SERVER_MODE": "true",
                "MCP_SERVER_ALLOWED_TOOLS": "calculate",
            },
            clear=False,
        ):
            call_resp = client.post(
                "/mcp/server",
                json={
                    "jsonrpc": "2.0",
                    "id": "3",
                    "method": "tools/call",
                    "params": {"name": "run_command", "arguments": {"command": "echo hi"}},
                },
            )
            self.assertEqual(call_resp.status_code, 200)
            err = call_resp.json().get("error", {})
            self.assertEqual(err.get("code"), -32001)

    def test_automation_callback_url_validation(self):
        invalid = client.post(
            "/integrations/automation/webhook",
            json={"task": "test", "callback_url": "ftp://evil.example/cb"},
        )
        self.assertEqual(invalid.status_code, 422)

        valid = client.post(
            "/integrations/automation/webhook",
            json={"task": "test", "callback_url": "https://example.com/cb"},
        )
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.json().get("run_id"))


if __name__ == "__main__":
    unittest.main()
