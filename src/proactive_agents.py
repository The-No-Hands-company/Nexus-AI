"""Proactive personal agents system.

Allows users to define background agents that run on schedules to perform
automated tasks like daily digests, monitoring, reminders, and workflow automation.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .agent import run_agent_task
from .scheduler import schedule_job, cancel_job, set_run_function
from .db import (
    load_pref as db_load_pref,
    save_pref as db_save_pref,
)
from .memory import add_memory, get_memory_context
from .tools_builtin import _tools as _builtin_tools
import logging
logger = logging.getLogger(__name__)

# Set up scheduler to run proactive agent jobs
def _setup_scheduler_run_function() -> None:
    """Set up the scheduler to execute proactive agent jobs."""
    def _proactive_agent_run_function(task: str) -> Any:
        """Run a proactive agent job based on task (job ID)."""
        try:
            job_id = task
            job = get_proactive_agent(job_id)
            if job and job.enabled:
                return _run_proactive_agent_job(job_id)
            else:
                return f"Proactive agent {job_id} not found or disabled"
        except Exception as e:
            return f"Error running proactive agent {task}: {str(e)}"
    
    set_run_function(_proactive_agent_run_function)


# Initialize the scheduler run function when this module is imported
_setup_scheduler_run_function()


# Storage key for proactive agent configurations
_PROACTIVE_AGENTS_KEY = "proactive_agents_v1"


@dataclass
class ProactiveAgentJob:
    """Configuration for a proactive agent job."""
    id: str
    user_id: str
    name: str
    prompt: str
    schedule: str  # Cron expression (e.g., "0 9 * * *" for 9 AM daily)
    enabled: bool = True
    tools: List[str] = field(default_factory=list)  # Tool names to allow
    context_sources: List[str] = field(default_factory=list)  # memory, calendar, etc.
    result_action: str = "store_memory"  # store_memory, notify, webhook
    result_target: str = ""  # memory category, webhook URL, etc.
    last_run: float = 0.0
    run_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _get_proactive_agents() -> List[Dict[str, Any]]:
    """Load all proactive agent configurations from storage."""
    raw = db_load_pref(_PROACTIVE_AGENTS_KEY, "[]")
    try:
        return json.loads(raw)
    except Exception:
        return []


def _save_proactive_agents(agents: List[Dict[str, Any]]) -> None:
    """Save proactive agent configurations to storage."""
    db_save_pref(_PROACTIVE_AGENTS_KEY, json.dumps(agents))


def create_proactive_agent(
    user_id: str,
    name: str,
    prompt: str,
    schedule: str,
    tools: List[str] | None = None,
    context_sources: List[str] | None = None,
    result_action: str = "store_memory",
    result_target: str = "",
    enabled: bool = True,
) -> ProactiveAgentJob:
    """Create a new proactive agent job.

    Args:
        user_id: The user ID
        name: Human-readable name for the agent
        prompt: The instruction/prompt for what the agent should do
        schedule: Cron expression (e.g., "0 9 * * *" for 9 AM daily)
        tools: List of tool names the agent is allowed to use
        context_sources: Sources of context to include (memory, calendar, email, etc.)
        result_action: What to do with results (store_memory, notify, webhook)
        result_target: Target for results (memory category, webhook URL, etc.)
        enabled: Whether the agent is initially enabled

    Returns:
        The created ProactiveAgentJob
    """
    agents = _get_proactive_agents()
    
    # Remove any existing agent with same name for this user
    agents = [a for a in agents if not (a["user_id"] == user_id and a["name"] == name)]
    
    job_id = str(uuid.uuid4())
    now = time.time()
    
    job = ProactiveAgentJob(
        id=job_id,
        user_id=user_id,
        name=name,
        prompt=prompt,
        schedule=schedule,
        enabled=enabled,
        tools=tools or [],
        context_sources=context_sources or [],
        result_action=result_action,
        result_target=result_target,
        created_at=now,
        updated_at=now,
    )
    
    agents.append({
        "id": job.id,
        "user_id": job.user_id,
        "name": job.name,
        "prompt": job.prompt,
        "schedule": job.schedule,
        "enabled": job.enabled,
        "tools": job.tools,
        "context_sources": job.context_sources,
        "result_action": job.result_action,
        "result_target": job.result_target,
        "last_run": job.last_run,
        "run_count": job.run_count,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "metadata": job.metadata,
    })
    
    _save_proactive_agents(agents)
    
    # Schedule the job if enabled
    if job.enabled:
        schedule_proactive_agent(job)
    
    return job


def get_proactive_agent(job_id: str) -> Optional[ProactiveAgentJob]:
    """Get a proactive agent by ID."""
    agents = _get_proactive_agents()
    for agent_data in agents:
        if agent_data["id"] == job_id:
            return _dict_to_job(agent_data)
    return None


def list_proactive_agents(user_id: str | None = None) -> List[ProactiveAgentJob]:
    """List proactive agents, optionally filtered by user."""
    agents = _get_proactive_agents()
    jobs = [_dict_to_job(a) for a in agents]
    if user_id is not None:
        jobs = [j for j in jobs if j.user_id == user_id]
    return jobs


def update_proactive_agent(job_id: str, **updates: Any) -> Optional[ProactiveAgentJob]:
    """Update a proactive agent job."""
    agents = _get_proactive_agents()
    job_dict = None
    
    for i, agent_data in enumerate(agents):
        if agent_data["id"] == job_id:
            # Update fields
            for key, value in updates.items():
                if key in agent_data:
                    agent_data[key] = value
            agent_data["updated_at"] = time.time()
            job_dict = agent_data
            agents[i] = agent_data
            break
    
    if job_dict is None:
        return None
    
    _save_proactive_agents(agents)
    
    # Reschedule if needed
    job = _dict_to_job(job_dict)
    if job.enabled:
        # Cancel existing schedule and reschedule
        cancel_proactive_agent(job_id)
        schedule_proactive_agent(job)
    else:
        # Disable - cancel any existing schedule
        cancel_proactive_agent(job_id)
    
    return job


def delete_proactive_agent(job_id: str) -> bool:
    """Delete a proactive agent job."""
    agents = _get_proactive_agents()
    original_len = len(agents)
    agents = [a for a in agents if a["id"] != job_id]
    
    if len(agents) < original_len:
        if len(agents) == 0:
            # No agents left, clear the preference entirely
            db_save_pref(_PROACTIVE_AGENTS_KEY, "[]")
        else:
            _save_proactive_agents(agents)
        cancel_proactive_agent(job_id)  # Cancel any scheduled job
        return True
    return False


def enable_proactive_agent(job_id: str) -> Optional[ProactiveAgentJob]:
    """Enable a proactive agent job."""
    job = update_proactive_agent(job_id, enabled=True)
    if job:
        schedule_proactive_agent(job)
    return job


def disable_proactive_agent(job_id: str) -> Optional[ProactiveAgentJob]:
    """Disable a proactive agent job."""
    job = update_proactive_agent(job_id, enabled=False)
    if job:
        cancel_proactive_agent(job_id)
    return job


def _dict_to_job(data: Dict[str, Any]) -> ProactiveAgentJob:
    """Convert dictionary to ProactiveAgentJob object."""
    return ProactiveAgentJob(
        id=data["id"],
        user_id=data["user_id"],
        name=data["name"],
        prompt=data["prompt"],
        schedule=data["schedule"],
        enabled=data["enabled"],
        tools=data.get("tools", []),
        context_sources=data.get("context_sources", []),
        result_action=data.get("result_action", "store_memory"),
        result_target=data.get("result_target", ""),
        last_run=data.get("last_run", 0.0),
        run_count=data.get("run_count", 0),
        created_at=data.get("created_at", time.time()),
        updated_at=data.get("updated_at", time.time()),
        metadata=data.get("metadata", {}),
    )


def schedule_proactive_agent(job: ProactiveAgentJob) -> None:
    """Schedule a proactive agent job to run according to its cron schedule."""
    if not job.enabled:
        return
    # Create a unique job ID for the scheduler
    # Define the job function
    
    # Define the job function
    def _proactive_agent_job_func():
        _run_proactive_agent_job(job.id)
    
    # Schedule using the existing scheduler
    schedule_job(
        name=f"Proactive Agent: {job.name}",
        task=job.id,
        schedule=job.schedule,
    )


def cancel_proactive_agent(job_id: str) -> None:
    """Cancel the scheduled job for a proactive agent."""
    scheduler_job_id = f"proactive_agent_{job_id}"
    try:
        cancel_job(scheduler_job_id)
    except Exception:
        # Job might not be scheduled, ignore
        pass


def _run_proactive_agent_job(job_id: str) -> None:
    """Execute a proactive agent job."""
    job = get_proactive_agent(job_id)
    if not job or not job.enabled:
        return
    
    try:
        # Update last run time
        job.last_run = time.time()
        job.run_count += 1
        
        # Track execution time for performance metrics
        start_time = time.time()
        
        # Gather context based on configured sources
        context_parts = []
        
        if "memory" in job.context_sources:
            # Get relevant memory based on the prompt
            memory_context = get_memory_context(job.prompt, max_tokens=2000)
            if memory_context:
                context_parts.append(f"Relevant memory:\n{memory_context}")
        
        if "time" in job.context_sources:
            # Add current time context
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            context_parts.append(f"Current time: {current_time}")
        
        if "system" in job.context_sources:
            # Add basic system context
            import platform
            context_parts.append(f"System: {platform.system()} {platform.release()}")
        
        # Add calendar context source
        if "calendar" in job.context_sources:
            try:
                from .service_integrations import fetch_calendar_events
                cal_result = fetch_calendar_events(user_id=job.user_id)
                if cal_result.success and cal_result.events:
                    event_lines = [
                        f"- {e.title} ({e.start} – {e.end})" 
                        for e in cal_result.events[:5]
                    ]
                    context_parts.append(
                        "Upcoming calendar events:\n" + "\n".join(event_lines)
                    )
                else:
                    context_parts.append(f"Calendar: {cal_result.error or 'No upcoming events found.'}")
            except Exception:
                logger.warning("Calendar service fetch failed", exc_info=True)
                context_parts.append("Calendar context: [Calendar service unavailable]")
        
        # Add email context source
        if "email" in job.context_sources:
            try:
                from .service_integrations import fetch_unread_emails
                email_result = fetch_unread_emails(user_id=job.user_id)
                if email_result.success and email_result.messages:
                    msg_lines = [
                        f"- {m.subject} (from: {m.sender})"
                        for m in email_result.messages[:5]
                    ]
                    context_parts.append(
                        "Recent unread emails:\n" + "\n".join(msg_lines)
                    )
                else:
                    context_parts.append(f"Email: {email_result.error or 'No unread emails found.'}")
            except Exception:
                logger.warning("Email service fetch failed", exc_info=True)
                context_parts.append("Email context: [Email service unavailable]")
        
        # Build the full prompt with context
        full_prompt = job.prompt
        if context_parts:
            full_prompt = f"""{job.prompt}
 
Context:
{chr(10).join(context_parts)}
 
Please perform the task based on the above context and instructions."""
        
        # Determine allowed tools
        allowed_tools = None
        if job.tools:
            # Filter to only allowed tools
            allowed_tool_names = set(job.tools)
            allowed_tools = {
                name: func for name, func in _builtin_tools.items()
                if name in allowed_tool_names
            }
        
        # Run the agent task
        result: Dict[str, Any] = run_agent_task(
            task=full_prompt,
            history=[],
            files=None,
            sid="",
            usage_principal="",
        )
        # Calculate execution time
        execution_time = time.time() - start_time
        
        # Update job metadata with execution time metrics
        if not job.metadata:
            job.metadata = {}
        if "execution_times" not in job.metadata:
            job.metadata["execution_times"] = []
        
        # Keep only the last 100 execution times to prevent unbounded growth
        job.metadata["execution_times"].append(execution_time)
        if len(job.metadata["execution_times"]) > 100:
            job.metadata["execution_times"] = job.metadata["execution_times"][-100:]
        
        # Calculate and store average execution time
        if job.metadata["execution_times"]:
            job.metadata["avg_execution_time"] = sum(job.metadata["execution_times"]) / len(job.metadata["execution_times"])
            job.metadata["last_execution_time"] = execution_time
        
        # Handle the result based on result_action
        if job.result_action == "store_memory":
            # Store result in memory
            result_content = f"Proactive agent '{job.name}' result:\n{result.result}"
            if job.result_target:
                # Store in specific category
                add_memory(result_content, tags=[job.result_target] if job.result_target else None)
            else:
                # Store in general memory
                add_memory(result_content)
        
        elif job.result_action == "notify":
            # Send notification via service integration
            try:
                from .service_integrations import send_notification
                notif_result = send_notification(
                    user_id=job.user_id,
                    title=f"Nexus AI: {job.name}",
                    body=str(result.result)[:500],
                    channel="push",
                )
                if notif_result.success:
                    logger.info("Notification sent for job %s", job.name)
                else:
                    logger.warning("Notification failed for job %s: %s", job.name, notif_result.errors)
            except Exception:
                logger.warning("Notification service unavailable for job %s", job.name, exc_info=True)
            notification_msg = f"[Proactive Agent Notification] {job.name}: {result.result}"
            # Also store in memory for user to see
            add_memory(notification_msg, tags=["notifications"])
        
        elif job.result_action == "webhook" and job.result_target:
            # Send webhook POST request
            try:
                import requests
                webhook_data = {
                    "agent_name": job.name,
                    "agent_id": job_id,
                    "result": result.result,
                    "timestamp": time.time(),
                    "user_id": job.user_id
                }
                response = requests.post(
                    job.result_target,
                    json=webhook_data,
                    timeout=10
                )
                response.raise_for_status()
                # Log successful webhook delivery
                webhook_msg = f"[Proactive Agent Webhook] Successfully sent to {job.result_target}"
                print(webhook_msg)
                add_memory(webhook_msg, tags=["webhook_logs"])
            except Exception as e:
                # Handle webhook delivery errors
                error_msg = f"[Proactive Agent Webhook Error] Failed to send to {job.result_target}: {str(e)}"
                print(error_msg)
                add_memory(error_msg, tags=["webhook_errors"])
        
        # Update the job with new run count and metadata
        update_proactive_agent(
            job_id,
            last_run=job.last_run,
            run_count=job.run_count,
            metadata=job.metadata,
        )
        
    except Exception as e:
        # Log error but don't crash the scheduler
        error_msg = f"[Proactive Agent Error] Job {job.name} ({job_id}) failed: {e}"
        print(error_msg)
        # Optionally store error in memory for user to see
        error_msg = f"Proactive agent '{job.name}' failed: {str(e)}"
        add_memory(error_msg, tags=["agent_errors"])


def run_proactive_agent_now(job_id: str) -> Dict[str, Any]:
    """Run a proactive agent job immediately (outside of schedule)."""
    job = get_proactive_agent(job_id)
    if not job:
        return {"error": "Agent not found"}
    
    if not job.enabled:
        return {"error": "Agent is disabled"}
    
    # Run the job synchronously and return result
    try:
        # Temporarily update last run
        old_last_run = job.last_run
        job.last_run = time.time()
        
        # Reuse the job execution logic
        _run_proactive_agent_job(job_id)
        
        # Restore original last run if needed (since _run_proactive_agent_job updates it)
        # Actually, we want to keep the updated time, so leave it
        
        return {"status": "completed", "message": f"Agent '{job.name}' executed successfully"}
    except Exception as e:
        return {"error": str(e)}


# ── Predefined agent templates ────────────────────────────────────────

def create_daily_digest_agent(
    user_id: str,
    name: str = "Daily Digest",
    sources: List[str] | None = None,
) -> ProactiveAgentJob:
    """Create a daily digest agent that summarizes the day's activities."""
    if sources is None:
        sources = ["memory"]
    
    prompt = """Create a concise daily digest summarizing:
1. Key activities and accomplishments from today
2. Important information gathered or learned
3. Pending tasks or follow-ups needed
4. Any patterns or insights observed

Format as a brief, readable summary suitable for morning or evening review."""
    
    return create_proactive_agent(
        user_id=user_id,
        name=name,
        prompt=prompt,
        schedule="0 20 * * *",  # 8 PM daily
        context_sources=sources,
        result_action="store_memory",
        result_target="digests",
    )


def create_task_reminder_agent(
    user_id: str,
    name: str = "Task Reminder",
    check_interval_hours: int = 4,
) -> ProactiveAgentJob:
    """Create an agent that reminds about pending tasks."""
    # Calculate cron expression from interval
    # For simplicity, we'll use every 4 hours: "0 */4 * * *"
    schedule = f"0 */{check_interval_hours} * * *"
    
    prompt = """Check for any pending tasks, deadlines, or commitments that need attention.
Look at:
- Recent messages and conversations
- Task lists and todo items
- Calendar events and deadlines
- Action items from meetings

If there are urgent or overdue items, highlight them clearly.
If everything is up to date, provide a brief confirmation."""
    
    return create_proactive_agent(
        user_id=user_id,
        name=name,
        prompt=prompt,
        schedule=schedule,
        result_action="notify",
    )


def create_learning_agent(
    user_id: str,
    name: str = "Learning Assistant",
    topic: str = "",
) -> ProactiveAgentJob:
    """Create an agent that helps with learning and knowledge retention."""
    if not topic:
        topic = "general knowledge and skills"
    
    prompt = f"""Help reinforce learning and retention about {topic} by:
1. Reviewing what was learned recently
2. Identifying gaps in understanding
3. Suggesting practice questions or exercises
4. Connecting new information to existing knowledge
5. Recommending resources for deeper study

Focus on active recall and spaced repetition principles."""
    
    return create_proactive_agent(
        user_id=user_id,
        name=name,
        prompt=prompt,
        schedule="0 9 * * *",  # 9 AM daily
        result_action="store_memory",
        result_target="learning",
    )


# ── Background worker ────────────────────────────────────────────────

def start_proactive_agent_worker() -> None:
    """Start the proactive agent background worker.
    This should be called once at application startup to load and schedule all agents."""
    agents = _get_proactive_agents()
    for agent in agents:
        if agent.enabled:
            schedule_proactive_agent(agent)


def stop_proactive_agent_worker() -> None:
    """Stop all proactive agent jobs."""
    agents = _get_proactive_agents()
    for agent in agents:
        cancel_proactive_agent(agent.id)


def clear_proactive_agent_cache() -> None:
    """Clear any cached data for proactive agents (useful for testing or memory management)."""
    # Clear any cached data structures if needed
    pass