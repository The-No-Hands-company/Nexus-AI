"""Tests for Claude-Code-inspired patterns adapted to NAI's zero-cost philosophy.

Covers: (#1) provider-usage token anchoring, (#4) layered compaction + circuit
breaker, (#5) tool-result budgeting with disk persistence.
"""
import json

import src.agent as agent


# ── #1: Provider usage anchoring ────────────────────────────────────────────

def test_call_openai_attaches_provider_usage(monkeypatch):
    """_call_openai should surface the provider's authoritative `usage` block."""
    fake_response = {
        "choices": [{"message": {"content": "hello world"}}],
        "usage": {"prompt_tokens": 1234, "completion_tokens": 56, "total_tokens": 1290},
    }
    monkeypatch.setattr(agent, "_do_openai_http_call", lambda url, headers, payload: fake_response)
    cfg = {
        "id": "llm7", "openai_compat": True, "base_url": "https://example/v1",
        "keyless": True, "local": False,
    }
    out = agent._call_openai(dict(cfg), [{"role": "user", "content": "hi"}], tools=None)
    assert out["_usage"]["prompt_tokens"] == 1234
    assert out["_usage"]["completion_tokens"] == 56
    assert out["_usage"]["total_tokens"] == 1290


def test_usage_from_action_prefers_real_counts():
    assert agent._usage_from_action({"_usage": {"prompt_tokens": 10, "completion_tokens": 4}})["completion_tokens"] == 4
    # No usage → None so callers fall back to estimation
    assert agent._usage_from_action({"action": "respond", "content": "x"}) is None
    assert agent._usage_from_action({"_usage": {"prompt_tokens": 0, "completion_tokens": 0}}) is None


def test_call_openai_without_usage_falls_back(monkeypatch):
    """Providers that omit usage must not crash — action just lacks _usage."""
    monkeypatch.setattr(
        agent, "_do_openai_http_call",
        lambda url, headers, payload: {"choices": [{"message": {"content": "ok"}}]},
    )
    cfg = {"id": "llm7", "openai_compat": True, "base_url": "https://example/v1"}
    out = agent._call_openai(dict(cfg), [{"role": "user", "content": "hi"}], tools=None)
    assert agent._usage_from_action(out) is None


# ── #2: Stable-prefix memoization ───────────────────────────────────────────

def test_prefix_memo_caches_and_clears(monkeypatch):
    agent.clear_prefix_memo()
    calls = {"n": 0}

    def _compute():
        calls["n"] += 1
        return f"value-{calls['n']}"

    first = agent._prefix_memoize("k", _compute)
    second = agent._prefix_memoize("k", _compute)
    assert first == second == "value-1"
    assert calls["n"] == 1, "second call should be served from memo, not recomputed"

    agent.clear_prefix_memo()
    third = agent._prefix_memoize("k", _compute)
    assert third == "value-2" and calls["n"] == 2


def test_custom_instructions_memoized(monkeypatch):
    agent.clear_prefix_memo()
    hits = {"n": 0}

    def _fake_load():
        hits["n"] += 1
        return "do the thing"

    monkeypatch.setattr(agent, "load_custom_instructions", _fake_load)
    assert agent._get_custom_instructions() == "do the thing"
    agent._get_custom_instructions()
    assert hits["n"] == 1, "custom instructions DB read should be memoized within TTL"


# ── #3: Per-invocation concurrency-safety classifier ────────────────────────

def test_read_only_actions_are_concurrency_safe():
    for act in ("read_file", "list_files", "web_search", "grep", "get_time", "git_status"):
        assert agent._is_tool_call_concurrency_safe({"action": act}), act


def test_mutating_actions_are_not_concurrency_safe():
    # Fail-closed: writes, deletes, network mutations, and unknowns → serial.
    for act in ("write_file", "delete_file", "commit_push", "clone_repo", "api_call", "totally_unknown_tool"):
        assert not agent._is_tool_call_concurrency_safe({"action": act}), act
    assert not agent._is_tool_call_concurrency_safe({})


def test_run_command_safety_inspects_the_command():
    safe = ["ls -la", "cat README.md", "grep -r foo .", "git status", "git log --oneline"]
    unsafe = [
        "rm -rf build", "mkdir out", "git push",
        "cat a && rm b",         # chaining
        "ls | xargs rm",          # pipe
        "echo hi > file",         # redirect
        "cat $(which python)",    # subshell
    ]
    for cmd in safe:
        assert agent._is_tool_call_concurrency_safe({"action": "run_command", "cmd": cmd}), cmd
    for cmd in unsafe:
        assert not agent._is_tool_call_concurrency_safe({"action": "run_command", "cmd": cmd}), cmd


# ── #4: Layered compaction + circuit breaker ────────────────────────────────

def _mk_history(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message number {i} " * 5} for i in range(n)]


def test_short_history_passes_through_untouched():
    h = _mk_history(10)
    assert agent._maybe_compress_history(h) == h


def test_moderate_history_uses_free_path_no_llm(monkeypatch):
    """21–40 messages must be compacted deterministically, never via the LLM."""
    called = {"llm": 0}
    monkeypatch.setattr(
        agent.CONTEXT_WINDOW, "compress_history_with_llm",
        lambda *a, **k: called.__setitem__("llm", called["llm"] + 1) or [],
    )
    out = agent._maybe_compress_history(_mk_history(30))
    assert called["llm"] == 0, "moderate histories must not spend LLM tokens"
    assert len(out) < 30
    assert out[0]["content"].startswith("[")  # boundary marker


def test_compaction_circuit_breaker_stops_after_failures(monkeypatch):
    agent._compact_breaker_reset()
    monkeypatch.setenv("NEXUS_LLM_COMPACT", "true")
    attempts = {"n": 0}

    def _boom(*a, **k):
        attempts["n"] += 1
        raise RuntimeError("summary provider down")

    monkeypatch.setattr(agent.CONTEXT_WINDOW, "compress_history_with_llm", _boom)
    big = _mk_history(60)
    # Each call fails and falls back to the free path; after MAX failures the
    # breaker opens and we stop calling the summarizer entirely.
    for _ in range(agent._COMPACT_MAX_FAILURES + 3):
        out = agent._maybe_compress_history(big)
        assert isinstance(out, list) and out  # always returns a usable history
    assert attempts["n"] == agent._COMPACT_MAX_FAILURES, "breaker must cap LLM retries"
    agent._compact_breaker_reset()


def test_compaction_breaker_resets_on_success(monkeypatch):
    agent._compact_breaker_reset()
    agent._compact_breaker_trip()
    agent._compact_breaker_trip()
    monkeypatch.setattr(agent.CONTEXT_WINDOW, "compress_history_with_llm", lambda *a, **k: [{"role": "system", "content": "summary"}])
    out = agent._maybe_compress_history(_mk_history(60))
    assert out == [{"role": "system", "content": "summary"}]
    assert agent._compact_breaker_ok()  # reset after a success


# ── #5: Tool-result budgeting ───────────────────────────────────────────────

def test_small_tool_result_passes_through(tmp_path):
    ctx, added = agent._budget_tool_result("short output", str(tmp_path), "read_file", 900, 0)
    assert ctx == "short output"
    assert added == len("short output")


def test_oversized_result_persisted_with_pointer(tmp_path):
    big = "X" * 5000
    ctx, added = agent._budget_tool_result(big, str(tmp_path), "read_file", 900, 0)
    assert "read_file to retrieve" in ctx
    assert len(ctx) < len(big), "context must hold a preview, not the full blob"
    # Full output must actually be on disk and complete.
    saved = list((tmp_path / ".nexus_tool_results").glob("read_file_*.txt"))
    assert len(saved) == 1
    assert saved[0].read_text() == big


def test_aggregate_budget_tightens_preview(tmp_path):
    big = "Y" * 5000
    # Under budget → normal 900 cap.
    ctx_lo, _ = agent._budget_tool_result(big, str(tmp_path), "grep", 900, 0)
    # Over aggregate budget → cap shrinks (300 floor), so preview is smaller.
    ctx_hi, _ = agent._budget_tool_result(big, str(tmp_path), "grep", 900, agent._TOOL_RESULT_AGG_BUDGET + 1)
    assert len(ctx_hi) < len(ctx_lo), "aggregate overrun must tighten previews"
