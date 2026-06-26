"""Tests for the nostack virtual team skill system."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── Skill discovery tests (no server needed) ──────────────────────────────


def test_discover_skills_returns_all_31():
    from nostack.registry import discover_skills

    skills = discover_skills()
    assert len(skills) == 31
    assert all(s.name for s in skills)


def test_get_skill_returns_correct_prompt():
    from nostack.registry import get_skill

    skill = get_skill("office-hours")
    assert skill is not None
    assert skill.name == "office-hours"
    assert "YC Office Hours" in skill.role
    assert "Six Forcing Questions" in skill.system_prompt


def test_get_skill_nonexistent_returns_none():
    from nostack.registry import get_skill

    assert get_skill("nonexistent") is None


def test_list_skill_names():
    from nostack.registry import list_skill_names

    names = list_skill_names()
    assert len(names) == 31
    assert "office-hours" in names
    assert "cso" in names
    assert "review" in names
    assert "autoplan" in names
    assert "spec" in names
    assert "learn" in names
    assert all(name and isinstance(name, str) for name in names)
    assert names == sorted(names)


def test_get_skill_prompt_returns_content():
    from nostack.registry import get_skill_prompt

    prompt = get_skill_prompt("cso")
    assert prompt is not None
    assert isinstance(prompt, str)
    assert "OWASP" in prompt
    assert "STRIDE" in prompt
    assert "Chief Security Officer" in prompt


def test_get_skill_agent_returns_agent():
    from nostack.registry import get_skill_agent
    from src.agents.registry import SpecialistAgent

    agent = get_skill_agent("review")
    assert agent is not None
    assert isinstance(agent, SpecialistAgent)
    assert agent.id == "nostack-review"
    assert agent.name == "Staff Engineer"


# ── API endpoint tests (uses TestClient) ──────────────────────────────────


@pytest.fixture
def client():
    from src.app import app

    return TestClient(app)


def test_list_skills_endpoint(client):
    response = client.get("/nostack/skills")
    assert response.status_code == 200
    data = response.json()
    assert "skills" in data
    assert data["total"] == 31


def test_get_skill_endpoint(client):
    response = client.get("/nostack/skills/office-hours")
    assert response.status_code == 200
    data = response.json()
    assert data["skill"] == "office-hours"
    assert "system_prompt" in data
    assert "Six Forcing Questions" in data["system_prompt"]


def test_get_skill_endpoint_404(client):
    response = client.get("/nostack/skills/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "error" in data


@pytest.mark.skip(reason="Requires running Nexus AI backend server")
def test_run_skill_endpoint_no_task(client):
    response = client.post(
        "/nostack/skills/office-hours/run",
        json={"task": ""},
    )
    assert response.status_code == 200
    data = response.json()
    # The run_skill endpoint always returns a dict with either result or error
    assert "error" in data or "result" in data


def test_sprint_endpoint_validation(client):
    response = client.post(
        "/nostack/sprint",
        json={"task": "some task"},
    )
    data = response.json()
    assert "error" in data
    assert "skills" in data["error"].lower() or "required" in data["error"].lower()


def test_sprint_endpoint_validation_no_task(client):
    response = client.post(
        "/nostack/sprint",
        json={"skills": ["office-hours"]},
    )
    data = response.json()
    assert "error" in data
    assert "task" in data["error"].lower() or "required" in data["error"].lower()


# ── Agent registration tests (Mock the registry) ─────────────────────────

# Import registry early to ensure nostack agents are registered before any
# API endpoint requests that might trigger sys.path mutations in _import_nostack().
from nostack.registry import register_nostack_agents
import src.agents.registry as _agent_reg


def test_nostack_agents_registered():
    """After register_nostack_agents(), verify nostack agents are in the registry."""
    register_nostack_agents()

    agents = _agent_reg.list_agents(include_extended=False)
    nostack_agents = [a for a in agents if a["id"].startswith("nostack-")]
    assert len(nostack_agents) >= 31


def test_get_specialist_returns_nostack_agent():
    """Verify get_specialist finds the nostack-cso agent."""
    agent = _agent_reg.get_specialist("nostack-cso")
    assert agent is not None
    assert agent.id == "nostack-cso"
    assert agent.name == "Chief Security Officer"


def test_classify_to_specialist_finds_nostack():
    """Verify keyword-based classification finds nostack agents."""
    agent = _agent_reg.classify_to_specialist(
        "security audit owasp vulnerability threat modeling"
    )
    assert agent is not None
    assert agent.id.startswith("nostack-") or agent.id == "security_auditor"


# ── Skill prompt format tests ─────────────────────────────────────────────


_SKILLS_DIR = Path(__file__).resolve().parent.parent / "nostack" / "skills"


def _all_skill_files():
    return sorted(_SKILLS_DIR.glob("*.md"))


def test_all_skills_have_role():
    skills = _all_skill_files()
    assert len(skills) == 31
    for skill_path in skills:
        content = skill_path.read_text(encoding="utf-8")
        assert "## Role" in content, f"{skill_path.name} missing ## Role section"


def test_all_skills_have_prompt():
    skills = _all_skill_files()
    assert len(skills) == 31
    for skill_path in skills:
        content = skill_path.read_text(encoding="utf-8")
        assert "## System Prompt" in content, (
            f"{skill_path.name} missing ## System Prompt section"
        )


def test_skill_names_are_valid():
    skills = _all_skill_files()
    assert len(skills) == 31
    for skill_path in skills:
        name = skill_path.stem
        assert name, f"{skill_path.name} has empty stem"
        assert not name.startswith("nostack-"), (
            f"{skill_path.name}: filename should not repeat nostack- prefix"
        )
        assert " " not in name, f"{skill_path.name} contains spaces"


# ── SprintState tests ─────────────────────────────────────────────────────


def test_sprint_state_creation():
    from nostack.sprint_state import SprintState

    state = SprintState(
        sprint_id="test-123",
        task="Build a login page",
        skills=["office-hours", "review", "ship"],
    )
    assert state.sprint_id == "test-123"
    assert state.task == "Build a login page"
    assert len(state.skills) == 3
    assert state.current_skill_index == 0
    assert state.status == "pending"
    assert len(state.results) == 0
    assert isinstance(state.created_at, float)
    assert isinstance(state.updated_at, float)


def test_sprint_state_defaults():
    from nostack.sprint_state import SprintState

    state = SprintState(task="Fix bug", skills=["investigate", "review", "ship"])
    assert state.sprint_id.startswith("sprint-")
    assert state.status == "pending"
    assert state.current_skill_index == 0
    assert state.results == []


def test_sprint_state_to_dict():
    from nostack.sprint_state import SprintState

    state = SprintState(
        sprint_id="test-456",
        task="Review PR",
        skills=["review"],
        current_skill_index=0,
        status="running",
    )
    d = state.to_dict()
    assert d["sprint_id"] == "test-456"
    assert d["task"] == "Review PR"
    assert d["skills"] == ["review"]
    assert d["status"] == "running"
    assert "created_at" in d
    assert "updated_at" in d


def test_sprint_state_save_and_load():
    from nostack.sprint_state import SprintState, create_sprint, load_sprint

    state = create_sprint(task="Test save/load", skills=["office-hours", "review"])
    assert state.sprint_id
    assert state.status == "pending"

    loaded = load_sprint(state.sprint_id)
    assert loaded is not None
    assert loaded.sprint_id == state.sprint_id
    assert loaded.task == "Test save/load"
    assert loaded.skills == ["office-hours", "review"]
    assert loaded.status == "pending"


def test_sprint_state_load_nonexistent():
    from nostack.sprint_state import load_sprint

    assert load_sprint("nonexistent-id") is None


def test_sprint_state_resume():
    from nostack.sprint_state import SprintState, create_sprint

    state = create_sprint(task="Resume test", skills=["office-hours", "review", "ship"])
    state.status = "failed"
    state.current_skill_index = 1
    state.results = [{"skill": "office-hours", "result": "some output", "status": "completed"}]
    state.save()

    resume_data = state.resume()
    assert resume_data["sprint_id"] == state.sprint_id
    assert resume_data["current_skill_index"] == 1
    assert resume_data["next_skill"] == "review"
    assert resume_data["remaining_skills"] == ["review", "ship"]


def test_sprint_state_resume_completed():
    from nostack.sprint_state import SprintState, create_sprint

    state = create_sprint(task="Done test", skills=["review"])
    state.status = "completed"
    state.save()

    resume_data = state.resume()
    assert resume_data["status"] == "completed"
    assert "Sprint already completed" in resume_data["message"]


def test_sprint_state_resume_cancelled():
    from nostack.sprint_state import SprintState, create_sprint

    state = create_sprint(task="Cancelled test", skills=["review"])
    state.status = "cancelled"
    state.save()

    resume_data = state.resume()
    assert resume_data["status"] == "cancelled"


def test_sprint_state_pending_skills():
    from nostack.sprint_state import SprintState

    state = SprintState(
        task="Test pending",
        skills=["a", "b", "c", "d"],
        current_skill_index=2,
    )
    assert state.pending_skills() == ["c", "d"]


def test_sprint_state_total_skills():
    from nostack.sprint_state import SprintState

    state = SprintState(task="Test count", skills=["a", "b", "c"])
    assert state.total_skills() == 3


def test_list_sprints():
    from nostack.sprint_state import create_sprint, list_sprints

    s1 = create_sprint(task="Sprint one", skills=["review"])
    s2 = create_sprint(task="Sprint two", skills=["office-hours"])

    sprints = list_sprints(limit=10)
    ids = [s.sprint_id for s in sprints]
    assert s1.sprint_id in ids
    assert s2.sprint_id in ids


def test_cancel_sprint():
    from nostack.sprint_state import create_sprint, load_sprint, cancel_sprint

    state = create_sprint(task="To cancel", skills=["review"])
    assert state.status == "pending"

    cancel_sprint(state.sprint_id)
    reloaded = load_sprint(state.sprint_id)
    assert reloaded is not None
    assert reloaded.status == "cancelled"


def test_cancel_sprint_nonexistent():
    from nostack.sprint_state import cancel_sprint
    import pytest

    with pytest.raises(ValueError, match="Sprint not found"):
        cancel_sprint("nonexistent-sprint")


# ── Sprint template tests ─────────────────────────────────────────────────


def test_sprint_templates_exist():
    from nostack.sprint_templates import SPRINT_TEMPLATES, TEMPLATE_METADATA

    assert len(SPRINT_TEMPLATES) == 7
    assert len(TEMPLATE_METADATA) == 7
    for key in SPRINT_TEMPLATES:
        assert key in TEMPLATE_METADATA, f"Missing metadata for template: {key}"


def test_list_templates():
    from nostack.sprint_templates import list_templates

    templates = list_templates()
    assert len(templates) == 7
    assert "feature" in templates
    assert templates["feature"]["skills"] == ["office-hours", "plan-ceo-review", "plan-eng-review", "review", "qa", "ship"]
    assert templates["bugfix"]["skills"] == ["investigate", "review", "ship"]
    assert templates["security"]["skills"] == ["cso", "review", "ship"]


def test_get_template_valid():
    from nostack.sprint_templates import get_template

    tmpl = get_template("bugfix")
    assert tmpl is not None
    assert tmpl["skills"] == ["investigate", "review", "ship"]
    assert tmpl["name"] == "bugfix"


def test_get_template_nonexistent():
    from nostack.sprint_templates import get_template

    assert get_template("nonexistent") is None


# ── Sprint API endpoint tests ─────────────────────────────────────────────


def test_sprint_endpoint_creates_and_returns_id(client):
    response = client.post(
        "/nostack/sprint",
        json={"task": "Build simple test feature", "skills": ["office-hours"]},
    )
    data = response.json()
    assert response.status_code == 200
    assert "sprint_id" in data
    assert data["sprint_id"].startswith("sprint-")
    assert data["status"] == "running"
    assert data["task"] == "Build simple test feature"
    assert data["skills"] == ["office-hours"]


def test_sprint_endpoint_with_template(client):
    response = client.post(
        "/nostack/sprint",
        json={"task": "Test docs", "template": "docs"},
    )
    data = response.json()
    assert response.status_code == 200
    assert "sprint_id" in data
    assert data["skills"] == ["document-generate", "document-release"]


def test_sprint_endpoint_template_not_found(client):
    response = client.post(
        "/nostack/sprint",
        json={"task": "Test", "template": "nonexistent"},
    )
    assert response.status_code == 404


def test_get_sprint_status(client):
    response = client.post(
        "/nostack/sprint",
        json={"task": "Status check test", "skills": ["review"]},
    )
    sprint_id = response.json()["sprint_id"]

    resp2 = client.get(f"/nostack/sprint/{sprint_id}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["sprint_id"] == sprint_id
    assert data2["task"] == "Status check test"


def test_get_sprint_not_found(client):
    response = client.get("/nostack/sprint/nonexistent-id")
    assert response.status_code == 404


def test_resume_completed_sprint(client):
    from nostack.sprint_state import create_sprint, load_sprint, cancel_sprint_background

    state = create_sprint(task="Resume completed", skills=["review"])
    cancel_sprint_background(state.sprint_id)
    state.status = "completed"
    state.save()

    resp2 = client.post(f"/nostack/sprint/{state.sprint_id}/resume")
    data2 = resp2.json()
    assert data2["status"] == "completed"
    assert "already completed" in data2["message"].lower()


def test_list_sprints_endpoint(client):
    resp = client.get("/nostack/sprints")
    assert resp.status_code == 200
    data = resp.json()
    assert "sprints" in data
    assert isinstance(data["sprints"], list)
    assert "total" in data


def test_cancel_sprint_endpoint(client):
    response = client.post(
        "/nostack/sprint",
        json={"task": "Cancel test", "skills": ["review"]},
    )
    sprint_id = response.json()["sprint_id"]

    resp2 = client.delete(f"/nostack/sprint/{sprint_id}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "cancelled"


def test_cancel_sprint_not_found(client):
    response = client.delete("/nostack/sprint/nonexistent-id")
    assert response.status_code == 404


def test_templates_endpoint(client):
    response = client.get("/nostack/templates")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert len(data["templates"]) == 7
    assert "feature" in data["templates"]
    assert "security" in data["templates"]
