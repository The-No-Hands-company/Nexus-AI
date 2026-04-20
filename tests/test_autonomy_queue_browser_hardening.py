import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app


client = TestClient(app)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_agent_bug_fix_checkpoint_and_rollback(monkeypatch):
    import src.db as db

    checkpoint_key = "agent_bug_fix_checkpoints_v1"
    db.save_pref(checkpoint_key, "[]")

    def _fake_llm(messages, task=""):
        return (
            {
                "content": (
                    '{"fixed_code":"print(123)","explanation":"fixed",'
                    '"changes":["adjusted print"],"confidence":0.93,"risk":"low"}'
                )
            },
            "pytest-provider",
        )

    monkeypatch.setattr("src.agent.call_llm_with_fallback", _fake_llm)

    fix = client.post(
        "/agent/bug-fix",
        json={
            "code": "print('x')",
            "error": "NameError: x",
            "language": "python",
            "test_command": "pytest -q",
        },
    )
    assert fix.status_code == 200
    payload = fix.json()
    assert payload["provider"] == "pytest-provider"
    assert payload["rollback_available"] is True
    checkpoint_id = payload["checkpoint_id"]

    listed = client.get("/agent/bug-fix/checkpoints?limit=10")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    detail = client.get(f"/agent/bug-fix/checkpoints/{checkpoint_id}")
    assert detail.status_code == 200
    assert detail.json()["checkpoint_id"] == checkpoint_id
    assert detail.json()["status"] in {"fixed", "review_required"}

    rollback = client.post(f"/agent/bug-fix/checkpoints/{checkpoint_id}/rollback")
    assert rollback.status_code == 200
    rb = rollback.json()
    assert rb["ok"] is True
    assert rb["checkpoint_id"] == checkpoint_id
    assert "restored_code" in rb


def test_agent_self_correct_endpoint(monkeypatch):
    def _fake_llm(messages, task=""):
        return ({"content": "{\"critique\":\"too vague\",\"revised\":\"better answer\",\"confidence\":0.84}"}, "pytest-provider")

    monkeypatch.setattr("src.agent.call_llm_with_fallback", _fake_llm)
    monkeypatch.setattr("src.thinking.parse_critique_response", lambda raw: {"critique": "too vague", "revised": "better answer", "confidence": 0.84})
    monkeypatch.setattr("src.thinking.build_critique_prompt", lambda answer, question: f"Critique: {question} :: {answer}")

    resp = client.post(
        "/agent/self-correct",
        json={
            "question": "How do I optimize this?",
            "answer": "Do it somehow",
            "confidence": 0.4,
            "threshold": 0.75,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["corrected"] is True
    assert payload["answer"] == "better answer"
    assert payload["provider"] == "pytest-provider"


def test_task_session_routes_and_runtime_status(monkeypatch):
    import src.task_queue as tq

    monkeypatch.setattr(tq, "start_worker", lambda: None)

    session_id = _unique("sess")

    created = client.post("/task-sessions", json={"session_id": session_id, "label": "batch"})
    assert created.status_code == 200
    assert created.json()["session_id"] == session_id

    submit = client.post(
        "/tasks/queue",
        json={
            "description": "session-task",
            "priority": 4,
            "metadata": {"session_id": session_id},
        },
    )
    assert submit.status_code == 200
    task_id = submit.json()["task_id"]

    status = client.get(f"/tasks/queue/{task_id}/status")
    assert status.status_code == 200
    sp = status.json()
    assert sp["task_id"] == task_id
    assert "queue_position" in sp
    assert "blocked_by" in sp
    assert "can_cancel" in sp

    sessions = client.get("/task-sessions?limit=20")
    assert sessions.status_code == 200
    assert any(row.get("session_id") == session_id for row in sessions.json().get("sessions", []))

    detail = client.get(f"/task-sessions/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["session_id"] == session_id
    assert detail.json()["total"] >= 1

    cancelled = client.post(f"/task-sessions/{session_id}/cancel", json={"include_running": True})
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] >= 1

    after = client.get(f"/tasks/queue/{task_id}/status")
    assert after.status_code == 200
    assert after.json()["status"] == "cancelled"


def test_browser_visual_detection_and_form_plan(monkeypatch):
    import src.browser_agent as ba

    monkeypatch.setattr(ba, "_detect_backend", lambda: "requests")
    monkeypatch.setattr(
        ba,
        "_requests_detect_elements",
        lambda url, max_elements=40: {
            "ok": True,
            "url": url,
            "elements": [
                {
                    "tag": "input",
                    "text": "",
                    "attrs": {"name": "email", "id": "", "class": "", "placeholder": "", "type": "text", "href": "", "action": ""},
                    "selector_candidates": ["input[name=\"email\"]"],
                },
                {
                    "tag": "button",
                    "text": "Send",
                    "attrs": {"name": "", "id": "", "class": "", "placeholder": "", "type": "submit", "href": "", "action": ""},
                    "selector_candidates": ["button:nth-of-type(1)"],
                },
            ],
            "forms": [{"form_selector": "form:nth-of-type(1)", "action": url, "method": "post"}],
            "backend": "requests",
            "count": 2,
        },
    )
    monkeypatch.setattr(
        ba,
        "_requests_navigate",
        lambda url: {
            "ok": True,
            "url": url,
            "title": "Page",
            "text_preview": "hello",
            "links": [{"text": "Docs", "href": "https://example.com/docs"}],
            "status_code": 200,
            "html": "<html><body><form><input name='email'/><input name='name'/><button type='submit'>Send</button></form></body></html>",
            "backend": "requests",
        },
    )

    created = client.post("/browser/sessions", json={"start_url": "https://example.com"})
    assert created.status_code == 200
    sid = created.json()["session_id"]

    detect = client.post(
        f"/browser/sessions/{sid}/visual-elements",
        json={"url": "https://example.com/form", "max_elements": 30},
    )
    assert detect.status_code == 200
    dp = detect.json()
    assert dp["ok"] is True
    assert isinstance(dp.get("result", {}).get("elements"), list)

    plan = client.post(
        f"/browser/sessions/{sid}/form-plan",
        json={
            "fields": {"email": "qa@example.com", "name": "QA"},
            "submit_selector": "button[type='submit']",
        },
    )
    assert plan.status_code == 200
    pp = plan.json()
    assert pp["ok"] is True
    assert "plan_id" in pp.get("result", {})

    execute = client.post(f"/browser/sessions/{sid}/form-plan/{pp['result']['plan_id']}/execute")
    assert execute.status_code == 400
    assert "requires playwright backend" in execute.json().get("error", "")
