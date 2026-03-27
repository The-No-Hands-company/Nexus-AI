"""
Agent memory — persists summaries of past conversations to disk.
On each new session, recent memories are injected as context.
"""
import os
import json
import time
from typing import List, Dict
from pathlib import Path

MEMORY_FILE = os.getenv("MEMORY_FILE", "/tmp/claude_alt_memory.json")
MAX_MEMORIES = 20        # keep last N conversation summaries
MEMORY_IN_CONTEXT = 5   # inject last N into each new conversation


def _load() -> List[Dict]:
    try:
        return json.loads(Path(MEMORY_FILE).read_text())
    except Exception:
        return []


def _save(memories: List[Dict]) -> None:
    Path(MEMORY_FILE).write_text(json.dumps(memories, indent=2))


def add_memory(summary: str, tags: List[str] | None = None) -> None:
    """Store a conversation summary."""
    memories = _load()
    memories.append({
        "ts":      time.time(),
        "summary": summary,
        "tags":    tags or [],
    })
    # Keep only the most recent
    memories = memories[-MAX_MEMORIES:]
    _save(memories)


def get_memory_context() -> str:
    """Return a formatted memory block to inject at the start of new sessions."""
    memories = _load()
    if not memories:
        return ""
    recent = memories[-MEMORY_IN_CONTEXT:]
    lines = ["[MEMORY — recent conversation summaries to give you context]"]
    for m in recent:
        ts = time.strftime("%Y-%m-%d", time.localtime(m["ts"]))
        lines.append(f"• {ts}: {m['summary']}")
    lines.append("")
    return "\n".join(lines)


def summarize_history(history: List[Dict], call_llm_fn) -> str:
    """
    Ask the LLM to produce a one-sentence summary of a completed conversation.
    call_llm_fn accepts a list of messages and returns (action_dict, provider_id).
    """
    if not history:
        return ""
    # Build a condensed transcript (user turns only, max 2000 chars)
    transcript = []
    for m in history:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            txt = m["content"][:200]
            if not txt.startswith("Tool result:") and not txt.startswith("Continue"):
                transcript.append(txt)
    if not transcript:
        return ""
    prompt = (
        "Summarize this conversation in ONE sentence (max 20 words), "
        "focusing on what was built or accomplished:\n\n"
        + "\n".join(f"- {t}" for t in transcript[-6:])
    )
    try:
        action, _ = call_llm_fn([{"role": "user", "content": prompt}])
        return action.get("content", "").strip()[:200]
    except Exception:
        return transcript[0][:100] if transcript else ""


def delete_all() -> None:
    try:
        Path(MEMORY_FILE).unlink()
    except Exception:
        pass


def get_all() -> List[Dict]:
    return _load()
