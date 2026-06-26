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
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
    assert "skills" in data["error"].lower() or "required" in data["error"].lower()


def test_sprint_endpoint_validation_no_task(client):
    response = client.post(
        "/nostack/sprint",
        json={"skills": ["office-hours"]},
    )
    assert response.status_code == 200
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
