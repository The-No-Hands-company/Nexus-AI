"""Tests for the native OpenAI function-calling path.

These verify:
  1. _call_openai sends a tools= array when one is provided.
  2. _call_openai converts a tool_calls response into an action dict.
  3. The legacy JSON-text path still works when tool_calls is absent.
  4. build_openai_tools() produces valid OpenAI function schemas.
  5. call_llm_with_fallback threads tools through to _call_single.
"""
import json
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(tool_calls=None, content="", status_code=200):
    """Build a minimal mock requests.Response for _call_openai."""
    msg: dict = {"content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    data = {"choices": [{"message": msg}]}
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    return resp


def _make_cfg(pid="openai"):
    return {
        "id": pid,
        "base_url": "https://api.openai.com/v1",
        "openai_compat": True,
        "local": False,
        "keyless": False,
    }


# ---------------------------------------------------------------------------
# 1. build_openai_tools
# ---------------------------------------------------------------------------

class TestBuildOpenAITools(unittest.TestCase):
    def test_returns_list_of_function_defs(self):
        from src.tools_builtin import build_openai_tools
        tools = build_openai_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 10, "Expected at least 10 tools")
        for t in tools:
            self.assertEqual(t["type"], "function")
            fn = t["function"]
            self.assertIn("name", fn)
            self.assertIn("description", fn)
            params = fn["parameters"]
            self.assertEqual(params["type"], "object")
            self.assertIn("properties", params)
            self.assertIn("required", params)

    def test_calculate_tool_present(self):
        from src.tools_builtin import build_openai_tools
        names = {t["function"]["name"] for t in build_openai_tools()}
        self.assertIn("calculate", names)

    def test_read_file_has_path_param(self):
        from src.tools_builtin import build_openai_tools
        tools = {t["function"]["name"]: t for t in build_openai_tools()}
        rf = tools["read_file"]["function"]
        self.assertIn("path", rf["parameters"]["properties"])
        self.assertIn("path", rf["parameters"]["required"])


# ---------------------------------------------------------------------------
# 2. _call_openai — sends tools in payload when provided
# ---------------------------------------------------------------------------

class TestCallOpenAISendsTools(unittest.TestCase):
    def _patch_and_call(self, tools, mock_response):
        """Run _call_openai with patched requests.post and return captured payload."""
        from src import agent as _agent
        captured = {}

        def fake_post(url, headers, data, timeout):
            captured["payload"] = json.loads(data)
            return mock_response

        with (
            patch.object(_agent, "_provider_api_key", return_value="test-key"),
            patch.object(_agent, "_provider_secret_name", return_value=None),
            patch.object(_agent, "_effective_model_for_provider", return_value="gpt-4o"),
            patch("requests.post", side_effect=fake_post),
        ):
            cfg = _make_cfg()
            result = _agent._call_openai(cfg, [{"role": "user", "content": "hi"}], tools=tools)

        return captured.get("payload", {}), result

    def test_tools_included_in_payload_when_provided(self):
        tools = [{"type": "function", "function": {"name": "calculate", "description": "math", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}}]
        resp = _make_response(tool_calls=[{
            "id": "call_test",
            "type": "function",
            "function": {"name": "calculate", "arguments": '{"expression":"2+2"}'},
        }])
        payload, _ = self._patch_and_call(tools, resp)
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["tools"][0]["function"]["name"], "calculate")

    def test_tools_not_in_payload_when_none(self):
        resp = _make_response(content='{"action":"respond","content":"hi"}')
        payload, _ = self._patch_and_call(None, resp)
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)


# ---------------------------------------------------------------------------
# 3. _call_openai — converts tool_calls response to action dict
# ---------------------------------------------------------------------------

class TestCallOpenAIParsesToolCalls(unittest.TestCase):
    def _call_with_tool_response(self, tool_name, args_dict):
        from src import agent as _agent
        tc = [{
            "id": "call_abc123",
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(args_dict)},
        }]
        resp = _make_response(tool_calls=tc)
        tools = [{"type": "function", "function": {"name": tool_name, "description": "x",
                  "parameters": {"type": "object", "properties": {}, "required": []}}}]

        with (
            patch.object(_agent, "_provider_api_key", return_value="k"),
            patch.object(_agent, "_provider_secret_name", return_value=None),
            patch.object(_agent, "_effective_model_for_provider", return_value="gpt-4o"),
            patch("requests.post", return_value=resp),
        ):
            cfg = _make_cfg()
            return _agent._call_openai(cfg, [{"role": "user", "content": "x"}], tools=tools)

    def test_action_set_from_tool_name(self):
        result = self._call_with_tool_response("read_file", {"path": "README.md"})
        self.assertEqual(result["action"], "read_file")

    def test_args_unpacked_into_result(self):
        result = self._call_with_tool_response("calculate", {"expression": "2+2"})
        self.assertEqual(result["expression"], "2+2")

    def test_native_tool_call_flag_set(self):
        result = self._call_with_tool_response("web_search", {"query": "nexus"})
        self.assertTrue(result.get("_native_tool_call"))

    def test_tool_call_id_preserved(self):
        result = self._call_with_tool_response("get_time", {})
        self.assertEqual(result["_tool_calls"][0]["id"], "call_abc123")


# ---------------------------------------------------------------------------
# 4. Legacy JSON path still works when no tool_calls in response
# ---------------------------------------------------------------------------

class TestCallOpenAILegacyPath(unittest.TestCase):
    def test_legacy_json_parsed_when_no_tool_calls(self):
        from src import agent as _agent
        content = '{"action":"respond","content":"hello"}'
        resp = _make_response(content=content)

        with (
            patch.object(_agent, "_provider_api_key", return_value="k"),
            patch.object(_agent, "_provider_secret_name", return_value=None),
            patch.object(_agent, "_effective_model_for_provider", return_value="gpt-4o"),
            patch("requests.post", return_value=resp),
        ):
            cfg = _make_cfg()
            result = _agent._call_openai(cfg, [{"role": "user", "content": "x"}])

        self.assertEqual(result["action"], "respond")
        self.assertEqual(result["content"], "hello")
        self.assertFalse(result.get("_native_tool_call", False))


# ---------------------------------------------------------------------------
# 5. call_llm_with_fallback passes tools to _call_single
# ---------------------------------------------------------------------------

class TestCallLLMWithFallbackPassesTools(unittest.TestCase):
    def test_tools_forwarded_to_call_single(self):
        from src import agent as _agent
        tools = [{"type": "function", "function": {"name": "calculate", "description": "x",
                  "parameters": {"type": "object", "properties": {}, "required": []}}}]
        captured = {}

        def fake_call_single(pid, msgs, t, sys_p):
            captured["tools"] = t
            captured["system_prompt"] = sys_p
            return {"action": "respond", "content": "ok"}

        with patch.object(_agent, "_call_single", side_effect=fake_call_single), \
             patch.object(_agent, "_smart_order", return_value=["openai"]), \
             patch.object(_agent, "_provider_temporarily_unavailable", return_value=False), \
             patch.object(_agent, "_provider_circuit") as mock_breaker:
            bc = MagicMock()
            bc.call.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
            bc.state = MagicMock(value="closed")
            mock_breaker.return_value = bc

            _agent.call_llm_with_fallback(
                [{"role": "user", "content": "x"}],
                task="test",
                tools=tools,
                system_prompt="sys",
            )

        self.assertIs(captured["tools"], tools)
        self.assertEqual(captured["system_prompt"], "sys")


if __name__ == "__main__":
    unittest.main()
