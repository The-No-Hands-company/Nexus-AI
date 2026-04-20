import uuid

from starlette.testclient import TestClient

from src.app import app
from src.db import delete_execution_trace, save_execution_trace


client = TestClient(app, raise_server_exceptions=True)


def _seed_trace(trace_id: str, events: list[dict]) -> None:
    save_execution_trace(trace_id, events)


def test_trace_search_export_diff_and_anomaly_endpoints():
    trace_a = f"trace-a-{uuid.uuid4().hex[:8]}"
    trace_b = f"trace-b-{uuid.uuid4().hex[:8]}"

    events_a = [
        {"type": "plan", "message": "start"},
        {"type": "tool", "action": "read_file", "result": "ok"},
        {"type": "error", "message": "transient failure"},
    ]
    events_b = [
        {"type": "plan", "message": "start"},
        {"type": "tool", "action": "write_file", "result": "ok"},
        {"type": "done", "message": "complete"},
    ]

    _seed_trace(trace_a, events_a)
    _seed_trace(trace_b, events_b)

    try:
        search = client.get("/tasks/search?event_type=error&limit=20")
        assert search.status_code == 200
        results = search.json().get("results", [])
        assert any(item.get("trace_id") == trace_a for item in results)

        export = client.get(f"/tasks/{trace_a}/export")
        assert export.status_code == 200
        export_payload = export.json()
        assert export_payload.get("trace_id") == trace_a
        assert len(export_payload.get("events", [])) == 3

        diff = client.get(f"/tasks/{trace_a}/diff?other_trace_id={trace_b}")
        assert diff.status_code == 200
        diff_payload = diff.json()
        assert diff_payload.get("trace_id") == trace_a
        assert "--- a/" in diff_payload.get("diff", "")

        anomalies = client.get("/tasks/anomalies?limit=20")
        assert anomalies.status_code == 200
        anomaly_items = anomalies.json().get("anomalies", [])
        assert any(item.get("trace_id") == trace_a for item in anomaly_items)
    finally:
        delete_execution_trace(trace_a)
        delete_execution_trace(trace_b)
