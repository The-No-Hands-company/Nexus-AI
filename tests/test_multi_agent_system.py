"""Tests for Section 10: Multi-Agent System.

Covers:
  10.1 Specialist registry — all 15 agents present
  10.2 Inter-agent bus — post, inbox, log, topic filter, DLQ
  10.3 Marketplace — list, publish, delete, reviews, versions, org filter
  10.4 Swarm / architecture — activity, health, pause/resume,
       blueprint CRUD, execute, export, import
"""
import json
import pytest
from starlette.testclient import TestClient

from src.app import app
from src.agent_bus import (
    AgentBus,
    post_message,
    read_messages,
    send_to_dlq,
    get_dlq,
    clear_dlq,
    recent_log,
)
from src.agents.registry import SPECIALIST_AGENTS, list_agents, get_specialist
from src.db import (
    save_marketplace_agent,
    load_marketplace_agents,
    delete_marketplace_agent,
    save_marketplace_agent_review,
    list_marketplace_agent_reviews,
    save_architecture_blueprint,
    load_architecture_blueprint,
    list_architecture_blueprints,
)

client = TestClient(app, raise_server_exceptions=True)

# ── 10.1  Specialist registry ─────────────────────────────────────────────────

EXPECTED_AGENT_IDS = {
    "architect",
    "security_auditor",
    "ui_ux_designer",
    "data_scientist",
    "legal_compliance",
    "product_manager",
    "debugger",
    "documentation_writer",
    "devops_infrastructure",
    "qa_testing",
    "marketing_copy",
    "finance_budget",
    "research_scientist",
    "accessibility_auditor",
    "code_reviewer",
}


def test_registry_contains_all_specialist_agents():
    ids = {a.id for a in SPECIALIST_AGENTS}
    missing = EXPECTED_AGENT_IDS - ids
    assert not missing, f"Missing agents: {missing}"


def test_registry_list_agents_serialisable():
    agents = list_agents()
    assert len(agents) == len(SPECIALIST_AGENTS)
    for a in agents:
        assert "id" in a and "name" in a and "system_prompt" not in a


def test_registry_get_specialist_returns_correct_agent():
    agent = get_specialist("legal_compliance")
    assert agent is not None
    assert agent.name == "Legal / Compliance Agent"
    assert "gdpr" in agent.keywords


def test_registry_get_specialist_returns_none_for_unknown():
    assert get_specialist("nonexistent_xyz") is None


def test_get_agents_endpoint():
    r = client.get("/agents")
    assert r.status_code == 200
    data = r.json()
    ids = {a["id"] for a in data["agents"]}
    assert EXPECTED_AGENT_IDS <= ids


# ── 10.2  Agent bus ───────────────────────────────────────────────────────────

def test_bus_post_and_read():
    bus = AgentBus()
    msg = bus.post("sender", "receiver", "hello world")
    assert msg.msg_id
    assert msg.topic == ""
    msgs = bus.read("receiver")
    assert len(msgs) == 1
    assert msgs[0].content == "hello world"


def test_bus_topic_filter_reads_only_matching_topic():
    bus = AgentBus()
    bus.post("a", "b", "no topic")
    bus.post("a", "b", "with topic", topic="tasks")
    bus.post("a", "b", "other topic", topic="alerts")

    task_msgs = bus.read("b", topic="tasks")
    assert len(task_msgs) == 1
    assert task_msgs[0].content == "with topic"


def test_bus_dlq_send_and_retrieve():
    bus = AgentBus()
    msg = bus.post("a", "b", "failed delivery")
    entry = bus.send_to_dlq(msg, reason="agent_offline")
    dlq = bus.get_dlq()
    assert any(e.msg.msg_id == msg.msg_id for e in dlq)
    assert any(e.reason == "agent_offline" for e in dlq)


def test_bus_dlq_clear():
    bus = AgentBus()
    msg = bus.post("a", "b", "fail")
    bus.send_to_dlq(msg, reason="test")
    cleared = bus.clear_dlq()
    assert cleared >= 1
    assert len(bus.get_dlq()) == 0


def test_get_bus_log_endpoint():
    post_message("e2e_sender", "e2e_receiver", "e2e test message", topic="e2e")
    r = client.get("/agents/bus/log?limit=100")
    assert r.status_code == 200
    data = r.json()
    assert "messages" in data
    assert "active_agents" in data


def test_get_bus_log_topic_filter_endpoint():
    post_message("filter_sender", "filter_receiver", "topic msg", topic="test_topic_xyz")
    r = client.get("/agents/bus/log?topic=test_topic_xyz&limit=50")
    assert r.status_code == 200
    data = r.json()
    assert all(m["topic"] == "test_topic_xyz" for m in data["messages"])


def test_get_bus_inbox_endpoint():
    post_message("inbox_sender", "inbox_agent_42", "test inbox")
    r = client.get("/agents/bus/inbox_agent_42")
    assert r.status_code == 200
    data = r.json()
    assert data["agent_id"] == "inbox_agent_42"
    assert isinstance(data["messages"], list)


def test_post_bus_message_endpoint():
    r = client.post("/agents/bus", json={
        "from_id": "test_sender",
        "to_id":   "test_receiver",
        "content": "hello from test",
        "topic":   "integration",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["from_id"] == "test_sender"
    assert data["topic"] == "integration"


def test_post_bus_message_validation():
    r = client.post("/agents/bus", json={"from_id": "x"})
    assert r.status_code == 422


def test_get_bus_dlq_endpoint():
    # Send a message to DLQ via module-level functions
    msg = post_message("dlq_sender", "dlq_recv", "failing msg")
    send_to_dlq(msg, reason="test_endpoint")
    r = client.get("/agents/bus/dlq")
    assert r.status_code == 200
    data = r.json()
    assert "dlq" in data
    assert "count" in data


def test_delete_bus_dlq_endpoint():
    r = client.delete("/agents/bus/dlq")
    assert r.status_code == 200
    data = r.json()
    assert "cleared" in data


# ── 10.3  Marketplace ─────────────────────────────────────────────────────────

def test_list_marketplace_agents_includes_builtins():
    r = client.get("/marketplace/agents")
    assert r.status_code == 200
    data = r.json()
    ids = {a["id"] for a in data["agents"]}
    assert "architect" in ids
    assert "legal_compliance" in ids


def test_publish_and_delete_marketplace_agent():
    agent_id = "test_mkt_agent_delete_me"
    r = client.post("/marketplace/agents", json={
        "id":            agent_id,
        "name":          "Test Agent",
        "system_prompt": "You are a test agent.",
    })
    assert r.status_code == 201

    r_list = client.get("/marketplace/agents")
    ids = {a["id"] for a in r_list.json()["agents"]}
    assert agent_id in ids

    r_del = client.delete(f"/marketplace/agents/{agent_id}")
    assert r_del.status_code == 200

    r_list2 = client.get("/marketplace/agents")
    ids2 = {a["id"] for a in r_list2.json()["agents"]}
    assert agent_id not in ids2


def test_marketplace_org_filter():
    save_marketplace_agent(
        agent_id="org_private_agent",
        name="Org Agent",
        icon="🔒",
        description="Private",
        system_prompt="You are private.",
        keywords=[],
        preferred_providers=[],
        temperature=0.1,
        tier="standard",
        source="org",
        org_id="test_org_123",
    )
    r_with = client.get("/marketplace/agents?org_id=test_org_123")
    assert r_with.status_code == 200
    ids_with = {a["id"] for a in r_with.json()["agents"]}
    assert "org_private_agent" in ids_with


def test_marketplace_agent_reviews_roundtrip():
    agent_id = "review_test_agent"
    save_marketplace_agent(
        agent_id=agent_id, name="Review Agent", icon="⭐",
        description="", system_prompt="Test.",
        keywords=[], preferred_providers=[],
        temperature=0.5, tier="standard",
    )
    r = client.post(f"/marketplace/agents/{agent_id}/reviews", json={
        "username": "tester",
        "rating":   5,
        "comment":  "Excellent!",
    })
    assert r.status_code == 201

    r_get = client.get(f"/marketplace/agents/{agent_id}/reviews")
    assert r_get.status_code == 200
    data = r_get.json()
    assert data["count"] >= 1
    assert data["average_rating"] == 5.0
    assert any(rv["username"] == "tester" for rv in data["reviews"])


def test_marketplace_agent_review_validation():
    r = client.post("/marketplace/agents/any_agent/reviews", json={
        "username": "tester",
        "rating":   10,  # out of range
    })
    assert r.status_code == 422


def test_marketplace_agent_versions():
    agent_id = "versioned_agent"
    save_marketplace_agent(
        agent_id=agent_id, name="V1", icon="🔢",
        description="", system_prompt="v1.",
        keywords=[], preferred_providers=[],
        temperature=0.1, tier="standard", version=1,
    )
    r = client.get(f"/marketplace/agents/{agent_id}/versions")
    assert r.status_code == 200
    data = r.json()
    assert data["agent_id"] == agent_id
    assert isinstance(data["versions"], list)
    assert len(data["versions"]) >= 1


def test_marketplace_import_url_rejects_http():
    r = client.post("/marketplace/agents/import-url", json={
        "url": "http://example.com/agent.json",
    })
    assert r.status_code == 422


def test_marketplace_import_url_missing_url():
    r = client.post("/marketplace/agents/import-url", json={})
    assert r.status_code == 422


# ── 10.4  Swarm / architecture ────────────────────────────────────────────────

def test_swarm_activity_endpoint():
    r = client.get("/swarm/activity")
    assert r.status_code == 200
    data = r.json()
    assert "events" in data


def test_swarm_health_endpoint():
    r = client.get("/swarm/health")
    assert r.status_code == 200
    data = r.json()
    assert "paused" in data
    assert "summary" in data
    assert "agents" in data


def test_swarm_pause_resume():
    r_pause = client.post("/swarm/pause")
    assert r_pause.status_code == 200
    assert r_pause.json()["paused"] is True

    r_health = client.get("/swarm/health")
    assert r_health.json()["paused"] is True

    r_resume = client.post("/swarm/resume")
    assert r_resume.status_code == 200
    assert r_resume.json()["paused"] is False

    r_health2 = client.get("/swarm/health")
    assert r_health2.json()["paused"] is False


def test_architecture_hierarchy_endpoint():
    r = client.get("/architecture/hierarchy")
    assert r.status_code == 200
    data = r.json()
    assert "foundation_models" in data or "agent_layer" in data or "system" in data


def test_blueprint_create_list_get():
    r_create = client.post("/architecture/blueprints", json={
        "name":  "test_blueprint_10",
        "notes": "created in test",
    })
    assert r_create.status_code == 200
    created = r_create.json()["blueprint"]
    assert created["name"] == "test_blueprint_10"
    assert created["version"] >= 1

    r_list = client.get("/architecture/blueprints")
    assert r_list.status_code == 200
    names = {b["name"] for b in r_list.json()["blueprints"]}
    assert "test_blueprint_10" in names

    r_get = client.get("/architecture/blueprints/test_blueprint_10")
    assert r_get.status_code == 200
    assert r_get.json()["name"] == "test_blueprint_10"


def test_blueprint_registry_endpoint():
    # Create a blueprint first to guarantee a registry entry
    client.post("/architecture/blueprints", json={"name": "registry_test_bp"})
    r = client.get("/architecture/registry/registry_test_bp")
    assert r.status_code == 200
    assert r.json()["name"] == "registry_test_bp"


def test_blueprint_404_on_unknown():
    r = client.get("/architecture/blueprints/does_not_exist_xyz")
    assert r.status_code == 404


def test_blueprint_execute_dispatches_agents():
    # Create a blueprint with a known snapshot containing agents
    snapshot = {
        "agent_layer": [
            {"id": "exec_agent_1", "name": "Exec 1", "role": "specialist"},
            {"id": "exec_agent_2", "name": "Exec 2", "role": "specialist"},
        ]
    }
    client.post("/architecture/blueprints", json={
        "name":         "exec_test_blueprint",
        "snapshot":     snapshot,
        "use_runtime":  False,
    })

    r = client.post("/architecture/blueprints/exec_test_blueprint/execute", json={
        "task": "Run the integration test",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    agent_ids = {d["agent_id"] for d in data["dispatched"]}
    assert {"exec_agent_1", "exec_agent_2"} == agent_ids


def test_blueprint_execute_fails_when_paused():
    # Pause swarm
    client.post("/swarm/pause")
    client.post("/architecture/blueprints", json={"name": "paused_bp"})
    r = client.post("/architecture/blueprints/paused_bp/execute")
    assert r.status_code == 409
    # Resume for subsequent tests
    client.post("/swarm/resume")


def test_blueprint_export_and_import():
    # Create blueprint with a clean, minimal snapshot (no runtime data that
    # contains base64 patterns which the safety middleware would flag).
    client.post("/architecture/blueprints", json={
        "name":        "exportable_bp",
        "notes":       "for export test",
        "use_runtime": False,
        "snapshot": {
            "agent_layer": [{"id": "export_agent", "name": "Export Agent"}],
        },
    })

    # Export
    r_export = client.get("/architecture/blueprints/exportable_bp/export")
    assert r_export.status_code == 200
    assert r_export.headers["content-type"].startswith("application/json")
    exported = r_export.json()
    assert exported["name"] == "exportable_bp"

    # Import under a new name
    exported["name"] = "imported_bp"
    r_import = client.post("/architecture/blueprints/import", json=exported)
    assert r_import.status_code == 201
    assert r_import.json()["blueprint"]["name"] == "imported_bp"

    # Verify the imported blueprint exists
    r_get = client.get("/architecture/blueprints/imported_bp")
    assert r_get.status_code == 200


def test_no_section_labeled_multi_agent_modules_remaining():
    """Guard: no section-numbered file names in src/agents or src/architecture."""
    import glob
    import os
    bad = (
        glob.glob("src/agents/section*.py")
        + glob.glob("src/architecture/section*.py")
    )
    assert bad == [], f"Section-numbered files found: {bad}"
