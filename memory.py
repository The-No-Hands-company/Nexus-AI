"""
Agent memory — persists conversation summaries via SQLite (db.py).
On each new session, recent memories are injected as context.
"""
import time
from typing import List, Dict
from db import (add_memory_entry, load_memory_entries,
                delete_all_memory as _db_delete_all)

MEMORY_IN_CONTEXT = 5   # inject last N into each new conversation


def add_memory(summary: str, tags: List[str] | None = None) -> None:
    add_memory_entry(summary, tags or [], time.time())


def get_memory_context() -> str:
    entries = load_memory_entries(MEMORY_IN_CONTEXT)
    if not entries:
        return ""
    entries = list(reversed(entries))   # oldest first
    lines = ["[MEMORY — recent conversation summaries to give you context]"]
    for m in entries:
        ts   = time.strftime("%Y-%m-%d", time.localtime(m["created_at"]))
        lines.append(f"• {ts}: {m['summary']}")
    lines.append("")
    return "\n".join(lines)


def summarize_history(history: List[Dict], call_llm_fn) -> str:
    if not history:
        return ""
    transcript = []
    for m in history:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            t = m["content"]
            if not t.startswith("Tool result:") and not t.startswith("Continue") \
               and not t.startswith("[MEMORY"):
                transcript.append(t[:200])
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
    _db_delete_all()


def get_all() -> List[Dict]:
    return load_memory_entries(50)
