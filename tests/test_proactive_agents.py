"""Tests for src/proactive_agents.py."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from src.proactive_agents import (
    ProactiveAgentJob,
    create_proactive_agent,
    delete_proactive_agent,
    disable_proactive_agent,
    enable_proactive_agent,
    get_proactive_agent,
    list_proactive_agents,
    run_proactive_agent_now,
    update_proactive_agent,
)


def test_create_proactive_agent():
    user_id = "test_user"
    job = create_proactive_agent(
        user_id=user_id,
        name="Test Agent",
        prompt="Say hello",
        schedule="0 9 * * *",
    )
    
    assert job.user_id == user_id
    assert job.name == "Test Agent"
    assert job.prompt == "Say hello"
    assert job.schedule == "0 9 * * *"
    assert job.enabled is True
    assert job.id is not None
    assert job.created_at > 0
    assert job.updated_at > 0


def test_get_proactive_agent():
    user_id = "test_user"
    job = create_proactive_agent(
        user_id=user_id,
        name="Test Get",
        prompt="Test",
        schedule="0 10 * * *",
    )
    
    retrieved = get_proactive_agent(job.id)
    assert retrieved is not None
    assert retrieved.id == job.id
    assert retrieved.name == "Test Get"


def test_list_proactive_agents():
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    user_id = f"test_user_{unique_id}"
    other_user_id = f"other_user_{unique_id}"
    # Create two agents
    job1 = create_proactive_agent(
        user_id=user_id,
        name="Agent 1",
        prompt="Test 1",
        schedule="0 9 * * *",
    )
    job2 = create_proactive_agent(
        user_id=user_id,
        name="Agent 2",
        prompt="Test 2",
        schedule="0 10 * * *",
    )
    
    # Create agent for different user
    other_job = create_proactive_agent(
        user_id=other_user_id,
        name="Other Agent",
        prompt="Test",
        schedule="0 11 * * *",
    )
    
    try:
        # List all agents
        all_agents = list_proactive_agents()
        assert len(all_agents) >= 2
        
        # List agents for specific user
        user_agents = list_proactive_agents(user_id=user_id)
        assert len(user_agents) == 2
        agent_names = {j.name for j in user_agents}
        assert agent_names == {"Agent 1", "Agent 2"}
    finally:
        # Clean up
        delete_proactive_agent(job1.id)
        delete_proactive_agent(job2.id)
        delete_proactive_agent(other_job.id)
def test_update_proactive_agent():
    user_id = "test_user"
    job = create_proactive_agent(
        user_id=user_id,
        name="Original Name",
        prompt="Original prompt",
        schedule="0 9 * * *",
    )
    
    # Update fields
    updated = update_proactive_agent(
        job.id,
        name="Updated Name",
        prompt="Updated prompt",
        enabled=False,
    )
    
    assert updated is not None
    assert updated.name == "Updated Name"
    assert updated.prompt == "Updated prompt"
    assert updated.enabled is False
    assert updated.updated_at > job.updated_at


def test_enable_disable_proactive_agent():
    user_id = "test_user"
    job = create_proactive_agent(
        user_id=user_id,
        name="Test Enable",
        prompt="Test",
        schedule="0 9 * * *",
        enabled=False,  # Start disabled
    )
    
    # Initially disabled
    assert job.enabled is False
    
    # Enable
    enabled_job = enable_proactive_agent(job.id)
    assert enabled_job is not None
    assert enabled_job.enabled is True
    
    # Disable
    disabled_job = disable_proactive_agent(job.id)
    assert disabled_job is not None
    assert disabled_job.enabled is False


def test_delete_proactive_agent():
    user_id = "test_user"
    job = create_proactive_agent(
        user_id=user_id,
        name="To Delete",
        prompt="Test",
        schedule="0 9 * * *",
    )
    
    # Verify it exists
    assert get_proactive_agent(job.id) is not None
    
    # Delete it
    result = delete_proactive_agent(job.id)
    assert result is True
    
    # Verify it's gone
    assert get_proactive_agent(job.id) is None


def test_run_proactive_agent_now():
    user_id = "test_user"
    job = create_proactive_agent(
        user_id=user_id,
        name="Test Run Now",
        prompt="What is 2+2?",
        schedule="0 9 * * *",
    )
    
    result = run_proactive_agent_now(job.id)
    assert "status" in result
    assert result["status"] == "completed"


def test_proactive_agent_job_dataclass():
    now = time.time()
    job = ProactiveAgentJob(
        id="test_id",
        user_id="test_user",
        name="Test Job",
        prompt="Test prompt",
        schedule="0 9 * * *",
        enabled=True,
        tools=["weather", "calculate"],
        context_sources=["memory"],
        result_action="store_memory",
        result_target="test_category",
        last_run=now - 3600,
        run_count=5,
        created_at=now - 7200,
        updated_at=now - 1800,
        metadata={"version": "1.0"},
    )
    
    assert job.id == "test_id"
    assert job.user_id == "test_user"
    assert job.name == "Test Job"
    assert job.prompt == "Test prompt"
    assert job.schedule == "0 9 * * *"
    assert job.enabled is True
    assert job.tools == ["weather", "calculate"]
    assert job.context_sources == ["memory"]
    assert job.result_action == "store_memory"
    assert job.result_target == "test_category"
    assert job.last_run == now - 3600
    assert job.run_count == 5
    assert job.created_at == now - 7200
    assert job.updated_at == now - 1800
    assert job.metadata == {"version": "1.0"}