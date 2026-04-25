import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.agent as agent


def test_try_direct_does_not_intercept_general_help_requests():
    assert agent._try_direct("Can you help me debug this traceback?") is None


def test_try_direct_still_handles_explicit_capability_query():
    response = agent._try_direct("help")
    assert isinstance(response, str)
    assert "I can help" in response


def test_run_agent_task_handles_empty_done_after_clarify(monkeypatch):
    def fake_stream(*args, **kwargs):
        yield {
            "type": "clarify",
            "questions": [{"id": "q1", "text": "Which file?", "options": ["A", "B"]}],
        }
        yield {
            "type": "done",
            "content": "",
            "provider": "test-provider",
            "model": "test-model",
            "history": [{"role": "assistant", "content": "clarify"}],
        }

    monkeypatch.setattr(agent, "stream_agent_task", fake_stream)
    result = agent.run_agent_task("ambiguous task", history=[])
    assert "Clarification required" in result["result"]
    assert result["provider"] == "test-provider"


def test_run_agent_task_handles_budget_exceeded_without_done(monkeypatch):
    def fake_stream(*args, **kwargs):
        yield {
            "type": "budget_exceeded",
            "reason": "max_tool_calls",
            "tool_calls": 12,
        }

    monkeypatch.setattr(agent, "stream_agent_task", fake_stream)
    result = agent.run_agent_task("do lots of tool work", history=[])
    assert "Execution budget reached" in result["result"]
    assert "tool calls" in result["result"].lower()
    assert result["model"] == "budget-guard"


def test_empty_clarify_for_repo_help_returns_actionable_starter(monkeypatch):
    def fake_stream(*args, **kwargs):
        yield {
            "type": "done",
            "content": "Yes, I will help with that task.",
            "provider": "test-provider",
            "model": "test-model",
            "history": [{"role": "assistant", "content": "starter"}],
        }

    # Validate helper behavior directly because the clarify fallback lives in stream_agent_task.
    assert agent._is_repo_collaboration_help_request(
        "please help me develop my game https://github.com/Zajfan/Cause-Of-Death"
    ) is True
    starter = agent._repo_collaboration_starter(
        "please help me develop my game https://github.com/Zajfan/Cause-Of-Death"
    )
    assert "Yes, I will help with that task." in starter
    assert "top priority" in starter

    monkeypatch.setattr(agent, "stream_agent_task", fake_stream)
    result = agent.run_agent_task(
        "please help me develop my game https://github.com/Zajfan/Cause-Of-Death",
        history=[],
    )
    assert "Yes, I will help with that task." in result["result"]


def test_provider_unavailable_message_for_repo_help_is_actionable():
    msg = agent._provider_unavailable_message(
        "help me develop my game https://github.com/Zajfan/Cause-Of-Death"
    )
    assert "Yes, I will help with that task." in msg
    assert "providers are currently unavailable" in msg


def test_provider_unavailable_message_for_general_tasks_stays_generic():
    msg = agent._provider_unavailable_message("what is a binary tree")
    assert "could not reach a model provider" in msg
    assert "built-in/keyless capabilities" in msg


def test_free_only_mode_forces_openrouter_free_model(monkeypatch):
    import copy

    called = {}

    class DummyResp:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": '{"action":"respond","content":"ok"}'}}]}

    def fake_post(url, headers=None, data=None, timeout=None):
        import json as _json

        called["payload"] = _json.loads(data.decode("utf-8"))
        return DummyResp()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(agent, "FREE_ONLY_MODE", True)

    cfg = copy.deepcopy(agent.PROVIDERS["openrouter"])
    cfg["default_model"] = "meta-llama/llama-3.3-70b-instruct:free"
    agent.update_config(model="openai/gpt-4o-mini")
    out = agent._call_openai(cfg, [{"role": "user", "content": "hi"}])

    assert out.get("action") == "respond"
    assert ":free" in called["payload"]["model"].lower()


def test_warmup_repeated_auth_failures_demote_provider(monkeypatch):
    pid = "openrouter"
    monkeypatch.setattr(agent, "WARMUP_DEMOTION_STRIKES", 2)
    monkeypatch.setattr(agent, "WARMUP_DEMOTION_SECONDS", 300)

    agent._provider_warmup_failure_strikes.pop(pid, None)
    agent._provider_demotion_until.pop(pid, None)
    agent._provider_demotion_reasons.pop(pid, None)

    agent._record_provider_failure(pid, "openai_compat_http_401: Unauthorized", source="warmup")
    assert agent._is_demoted(pid) is False

    agent._record_provider_failure(pid, "openai_compat_http_401: Unauthorized", source="warmup")
    assert agent._is_demoted(pid) is True
    assert agent._provider_demotion_reasons.get(pid) == "warmup_auth"


def test_free_provider_diagnostics_has_summary():
    diag = agent.get_free_provider_diagnostics()
    assert "summary" in diag
    assert "providers" in diag
    assert isinstance(diag["providers"], list)


def test_paid_providers_require_explicit_opt_in():
    """Paid providers must have opt_in:True and must not appear in routing without a key."""
    always_paid = ["openai", "claude", "grok", "gemini", "mistral", "deepseek", "openrouter"]
    for pid in always_paid:
        cfg = agent.PROVIDERS.get(pid)
        assert cfg is not None, f"Missing provider entry: {pid}"
        assert cfg.get("opt_in") is True, f"{pid} should have opt_in:True"

    # Without keys configured, routing must not include any opt_in provider.
    import unittest.mock as mock
    with mock.patch("src.agent._provider_api_key", return_value=""):
        order = agent._smart_order("hello world")
    for pid in order:
        cfg = agent.PROVIDERS.get(pid, {})
        assert not cfg.get("opt_in", False), (
            f"Opt-in provider '{pid}' appeared in routing without a key"
        )
