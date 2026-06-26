"""Tests for src/routes/browser.py.

Covers browser session lifecycle, step execution, and confirmation flows.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


# ── Session lifecycle ───────────────────────────────────────────────────────


def test_browser_create_session(client):
    mock_create = MagicMock(return_value={"session_id": "abc", "ok": True})
    with patch("src.browser_agent.create_session", mock_create):
        resp = client.post(
            "/browser/sessions",
            json={"start_url": "https://example.com"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "abc"


def test_browser_create_session_default_url(client):
    mock_create = MagicMock(return_value={"session_id": "def", "ok": True})
    with patch("src.browser_agent.create_session", mock_create):
        resp = client.post("/browser/sessions", json={})
    assert resp.status_code == 200
    _, kwargs = mock_create.call_args
    assert kwargs["start_url"] == "https://example.com"


def test_browser_list_sessions(client):
    mock_list = MagicMock(return_value=[{"session_id": "abc"}, {"session_id": "def"}])
    with patch("src.browser_agent.list_sessions", mock_list):
        resp = client.get("/browser/sessions")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 2


def test_browser_get_session_found(client):
    mock_get = MagicMock(return_value={"session_id": "abc", "status": "running"})
    with patch("src.browser_agent.get_session", mock_get):
        resp = client.get("/browser/sessions/abc")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "abc"


def test_browser_get_session_not_found(client):
    mock_get = MagicMock(return_value=None)
    with patch("src.browser_agent.get_session", mock_get):
        resp = client.get("/browser/sessions/nonexistent")
    assert resp.status_code == 404


# ── Step execution ──────────────────────────────────────────────────────────


def test_browser_step_success(client):
    mock_execute = AsyncMock(return_value={"ok": True, "result": "navigated"})
    with patch("src.browser_agent.execute_step", mock_execute):
        resp = client.post(
            "/browser/sessions/abc/step",
            json={"action": "navigate", "params": {"url": "https://example.com"}},
        )
    assert resp.status_code == 200
    assert resp.json()["result"] == "navigated"


def test_browser_step_failure(client):
    mock_execute = AsyncMock(return_value={"ok": False, "error": "navigation failed"})
    with patch("src.browser_agent.execute_step", mock_execute):
        resp = client.post(
            "/browser/sessions/abc/step",
            json={"action": "navigate", "params": {}},
        )
    assert resp.status_code == 400


# ── Confirmation flow ───────────────────────────────────────────────────────


def test_browser_confirm_approved(client):
    mock_confirm = AsyncMock(return_value={"ok": True, "approved": True})
    with patch("src.browser_agent.confirm_pending_step", mock_confirm):
        resp = client.post(
            "/browser/sessions/abc/confirm",
            json={"approve": True, "actor": "user1"},
        )
    assert resp.status_code == 200


def test_browser_confirm_rejected(client):
    mock_confirm = AsyncMock(return_value={"ok": False, "error": "already expired"})
    with patch("src.browser_agent.confirm_pending_step", mock_confirm):
        resp = client.post(
            "/browser/sessions/abc/confirm",
            json={"approve": False},
        )
    assert resp.status_code == 400


# ── Pause / Resume ──────────────────────────────────────────────────────────


def test_browser_pause_success(client):
    mock_pause = MagicMock(return_value={"ok": True, "status": "paused"})
    with patch("src.browser_agent.pause_session", mock_pause):
        resp = client.post(
            "/browser/sessions/abc/pause",
            json={"reason": "manual_review"},
        )
    assert resp.status_code == 200


def test_browser_pause_not_found(client):
    mock_pause = MagicMock(return_value={"ok": False, "error": "session not found"})
    with patch("src.browser_agent.pause_session", mock_pause):
        resp = client.post("/browser/sessions/abc/pause", json={})
    assert resp.status_code == 404


def test_browser_resume_success(client):
    mock_resume = MagicMock(return_value={"ok": True, "status": "running"})
    with patch("src.browser_agent.resume_session", mock_resume):
        resp = client.post(
            "/browser/sessions/abc/resume",
            json={"replay_navigation": True},
        )
    assert resp.status_code == 200


def test_browser_resume_failure(client):
    mock_resume = MagicMock(return_value={"ok": False, "error": "session not paused"})
    with patch("src.browser_agent.resume_session", mock_resume):
        resp = client.post("/browser/sessions/abc/resume", json={})
    assert resp.status_code == 404


# ── History and visual elements ─────────────────────────────────────────────


def test_browser_history(client):
    mock_history = MagicMock(return_value=[{"url": "https://example.com"}])
    with patch("src.browser_agent.get_navigation_history", mock_history):
        resp = client.get("/browser/sessions/abc/history")
    assert resp.status_code == 200
    assert len(resp.json()["history"]) == 1


def test_browser_visual_elements_success(client):
    mock_execute = AsyncMock(return_value={"ok": True, "elements": ["button", "input"]})
    with patch("src.browser_agent.execute_step", mock_execute):
        resp = client.post(
            "/browser/sessions/abc/visual-elements",
            json={"url": "https://example.com", "max_elements": 20},
        )
    assert resp.status_code == 200


def test_browser_visual_elements_failure(client):
    mock_execute = AsyncMock(return_value={"ok": False, "error": "detection failed"})
    with patch("src.browser_agent.execute_step", mock_execute):
        resp = client.post(
            "/browser/sessions/abc/visual-elements",
            json={},
        )
    assert resp.status_code == 400


# ── Form plan ───────────────────────────────────────────────────────────────


def test_browser_form_plan_success(client):
    mock_execute = AsyncMock(return_value={"ok": True, "plan_id": "plan-1"})
    with patch("src.browser_agent.execute_step", mock_execute):
        resp = client.post(
            "/browser/sessions/abc/form-plan",
            json={"fields": {"name": "#name", "email": "#email"}},
        )
    assert resp.status_code == 200


def test_browser_execute_form_plan_success(client):
    mock_execute = AsyncMock(return_value={"ok": True, "result": "form filled"})
    with patch("src.browser_agent.execute_step", mock_execute):
        resp = client.post(
            "/browser/sessions/abc/form-plan/plan-1/execute",
            json={},
        )
    assert resp.status_code == 200


def test_browser_execute_form_plan_failure(client):
    mock_execute = AsyncMock(return_value={"ok": False, "error": "plan expired"})
    with patch("src.browser_agent.execute_step", mock_execute):
        resp = client.post(
            "/browser/sessions/abc/form-plan/plan-1/execute",
            json={},
        )
    assert resp.status_code == 400
