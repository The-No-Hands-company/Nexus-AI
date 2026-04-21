import sys
import secrets
import string
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app
from src.api.routes import _make_token


client = TestClient(app)


def _uid(prefix: str) -> str:
    suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
    return f"{prefix}-{suffix}"


def test_agent_bus_long_poll_consume_returns_unread_message():
    sender = _uid("sender")
    receiver = _uid("receiver")

    posted = client.post(
        "/agents/bus",
        json={
            "from_id": sender,
            "to_id": receiver,
            "content": "hello from async bus",
            "topic": "coord",
        },
    )
    assert posted.status_code == 201

    consumed = client.get(
        f"/agents/bus/consume?agent_id={receiver}&wait_seconds=0.2&limit=10&topic=coord"
    )
    assert consumed.status_code == 200
    payload = consumed.json()
    assert payload["timed_out"] is False
    assert len(payload["messages"]) >= 1
    assert payload["messages"][0]["content"] == "hello from async bus"


def test_agent_bus_websocket_consumer_streams_message():
    sender = _uid("ws-sender")
    receiver = _uid("ws-receiver")

    with client.websocket_connect(f"/agents/bus/ws/{receiver}?poll_ms=50") as ws:
        posted = client.post(
            "/agents/bus",
            json={
                "from_id": sender,
                "to_id": receiver,
                "content": "ws payload",
                "topic": "ws-topic",
            },
        )
        assert posted.status_code == 201
        event = ws.receive_json()
        assert event["type"] == "message"
        assert event["message"]["content"] == "ws payload"


def test_lineage_link_and_graph_query_roundtrip():
    root = _uid("root")
    child_a = _uid("child")
    child_b = _uid("child")

    r1 = client.post(
        "/agents/lineage/links",
        json={
            "parent_task_id": root,
            "child_task_id": child_a,
            "relation": "spawned_by",
        },
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/agents/lineage/links",
        json={
            "parent_task_id": child_a,
            "child_task_id": child_b,
            "relation": "next",
        },
    )
    assert r2.status_code == 201

    graph = client.get(f"/agents/lineage/graph/{root}?depth=4")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["root_task_id"] == root
    node_ids = {row["task_id"] for row in payload["nodes"]}
    assert root in node_ids
    assert child_a in node_ids
    assert child_b in node_ids

    query = client.get(f"/agents/lineage/query?task_id={child_a}&direction=both")
    assert query.status_code == 200
    assert query.json()["count"] >= 2


def test_autonomy_execute_records_lineage_edges(monkeypatch):
    class DummyOrchestrator:
        def __init__(self, llm, max_parallel=2):
            self.llm = llm
            self.max_parallel = max_parallel

        def execute(self, goal, config):
            return {
                "result": "ok",
                "plan_summary": "stub",
                "execution_time": 0.01,
                "subtasks": [
                    {"id": _uid("subtask"), "name": "one"},
                    {"id": _uid("subtask"), "name": "two"},
                ],
            }

    monkeypatch.setattr("src.api.routes.Orchestrator", DummyOrchestrator)

    resp = client.post("/autonomy/execute", json={"goal": "Draft release plan", "max_subtasks": 2})
    assert resp.status_code == 200
    trace_id = resp.json()["trace_id"]

    lineage = client.get(f"/agents/lineage/query?task_id={trace_id}&direction=downstream")
    assert lineage.status_code == 200
    assert lineage.json()["count"] >= 2


def test_graphql_read_models_and_usage_auth_boundary():
    q = "{ health models providers }"
    resp = client.post("/graphql", json={"query": q})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["health"]["status"] == "ok"
    assert isinstance(data["models"], list)
    assert isinstance(data["providers"], dict)
    assert isinstance(data["providers"].get("providers"), list)

    q_usage = "{ usage }"
    no_admin = client.post("/graphql", json={"query": q_usage})
    assert no_admin.status_code == 200
    assert "errors" in no_admin.json()

    admin_headers = {"Authorization": f"Bearer {_make_token('graphql-admin', role='admin')}"}
    with_admin = client.post("/graphql", json={"query": q_usage}, headers=admin_headers)
    assert with_admin.status_code == 200
    assert "usage" in with_admin.json()["data"]
