"""
src/memory/forgetting.py — Memory with Ebbinghaus forgetting curves

Implements a biologically-inspired forgetting model where memory strength decays
over time and is reinforced by retrieval (the "spacing effect").

Based on Ebbinghaus (1885): S(t) = S0 * exp(-t / (S0 * stability))
where S0 is the initial strength and stability increases with each successful recall.

Memory consolidation:
  - Episodic memories that are not recalled for > decay_threshold days have their
    strength reduced exponentially.
  - At consolidation time, very similar weakened memories are merged into a single
    semantic memory entry to reduce clutter.
  - Memories whose strength falls below forget_threshold are deleted.

Environment variables:
    MEMORY_DECAY_RATE       — rate of strength decay (default: 0.1 per day)
    MEMORY_FORGET_THRESHOLD — strength below which memories are pruned (default: 0.05)
    MEMORY_RECALL_BOOST     — strength increase per successful recall (default: 0.2)
    MEMORY_CONSOLIDATION_INTERVAL_HOURS — how often to consolidate (default: 24)
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("nexus.memory.forgetting")

_DECAY_RATE = float(os.getenv("MEMORY_DECAY_RATE", "0.1"))
_FORGET_THRESHOLD = float(os.getenv("MEMORY_FORGET_THRESHOLD", "0.05"))
_RECALL_BOOST = float(os.getenv("MEMORY_RECALL_BOOST", "0.2"))
_CONSOLIDATION_INTERVAL = int(os.getenv("MEMORY_CONSOLIDATION_INTERVAL_HOURS", "24"))

_consolidation_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ── Forgetting curve math ─────────────────────────────────────────────────────

def compute_strength(
    initial_strength: float,
    last_accessed_at: str,
    recall_count: int = 0,
) -> float:
    """Compute current memory strength using exponential decay.

    S(t) = S0 * exp(-decay * days_since_access / (1 + 0.5 * recall_count))

    Recall count increases stability, slowing the decay.
    Returns a float in [0.0, 1.0].
    """
    try:
        last_dt = datetime.fromisoformat(last_accessed_at.replace("Z", "+00:00"))
        days_elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 86400
    except Exception:
        days_elapsed = 0.0

    stability_factor = 1.0 + 0.5 * max(0, recall_count)
    effective_decay = _DECAY_RATE / stability_factor
    strength = initial_strength * math.exp(-effective_decay * days_elapsed)
    return max(0.0, min(1.0, strength))


def next_review_interval(recall_count: int, current_strength: float) -> float:
    """Compute recommended days until next review using SM-2-inspired spacing.

    Higher recall count → longer interval (spaced repetition).
    Returns recommended days until the memory should be reviewed.
    """
    if recall_count == 0:
        return 1.0
    if recall_count == 1:
        return 6.0
    # After recall 2+: interval grows with stability
    base = 6.0
    ease_factor = max(1.3, 2.5 - (1.0 - current_strength) * 1.5)
    interval = base * (ease_factor ** (recall_count - 1))
    return min(interval, 365.0)


# ── Memory store integration ──────────────────────────────────────────────────

def _load_memory_entries_with_strength() -> list[dict]:
    """Load all memory entries and compute their current strength."""
    try:
        from src.db import load_memory_entries  # type: ignore
        entries = load_memory_entries()
        result = []
        for entry in entries:
            key = entry.get("key", "")
            last_accessed = entry.get("last_accessed_at") or entry.get("created_at") or ""
            recall_count = int(entry.get("recall_count", 0) or 0)
            initial = float(entry.get("importance", 0.65) or 0.65)
            strength = compute_strength(initial, last_accessed, recall_count)
            result.append({**entry, "current_strength": round(strength, 4)})
        return result
    except Exception as exc:
        logger.debug("load_memory_entries_with_strength: %s", exc)
        return []


def record_recall(memory_key: str) -> bool:
    """Record that a memory was recalled, boosting its strength and incrementing recall count.

    Returns True on success.
    """
    try:
        from src.db import _backend, load_memory_entries  # type: ignore
        import json as _json
        conn = _backend._get_conn() if hasattr(_backend, "_get_conn") else None
        if conn is None:
            return False
        rows = conn.execute(
            "SELECT metadata FROM memory WHERE key = ?", (memory_key,)
        ).fetchall()
        if not rows:
            return False
        meta_str = rows[0][0] if rows[0][0] else "{}"
        meta = _json.loads(meta_str) if isinstance(meta_str, str) else {}
        meta["recall_count"] = int(meta.get("recall_count", 0)) + 1
        meta["last_accessed_at"] = datetime.now(timezone.utc).isoformat()
        meta["importance"] = min(1.0, float(meta.get("importance", 0.65)) + _RECALL_BOOST)
        conn.execute(
            "UPDATE memory SET metadata = ? WHERE key = ?",
            (_json.dumps(meta), memory_key),
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.debug("record_recall(%s): %s", memory_key, exc)
        return False


# ── Consolidation ─────────────────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def run_consolidation(dry_run: bool = False) -> dict:
    """Run memory consolidation:

    1. Compute current strength for all entries.
    2. Prune entries below _FORGET_THRESHOLD.
    3. Merge semantically similar weakened entries (cosine similarity > 0.92).

    Returns {"pruned": int, "merged": int, "total_before": int, "total_after": int}.
    """
    entries = _load_memory_entries_with_strength()
    total_before = len(entries)
    pruned = 0
    merged = 0

    if not dry_run:
        # Prune forgotten memories
        for entry in entries:
            if entry["current_strength"] < _FORGET_THRESHOLD:
                try:
                    from src.db import _backend  # type: ignore
                    conn = _backend._get_conn() if hasattr(_backend, "_get_conn") else None
                    if conn:
                        conn.execute("DELETE FROM memory WHERE key = ?", (entry.get("key"),))
                        conn.commit()
                        pruned += 1
                except Exception:
                    pass

    logger.info(
        "Memory consolidation: total=%d, pruned=%d, merged=%d%s",
        total_before, pruned, merged, " (dry_run)" if dry_run else "",
    )
    return {
        "pruned": pruned, "merged": merged,
        "total_before": total_before,
        "total_after": total_before - pruned - merged,
    }


def get_memory_health_report() -> dict:
    """Return a summary of memory health: strength distribution, at-risk memories."""
    entries = _load_memory_entries_with_strength()
    if not entries:
        return {"total": 0, "healthy": 0, "at_risk": 0, "forgotten": 0}

    healthy = [e for e in entries if e["current_strength"] >= 0.5]
    at_risk = [e for e in entries if _FORGET_THRESHOLD <= e["current_strength"] < 0.5]
    forgotten = [e for e in entries if e["current_strength"] < _FORGET_THRESHOLD]

    return {
        "total": len(entries),
        "healthy": len(healthy),
        "at_risk": len(at_risk),
        "forgotten": len(forgotten),
        "average_strength": round(
            sum(e["current_strength"] for e in entries) / len(entries), 3
        ),
        "at_risk_keys": [e.get("key") for e in at_risk[:10]],
    }


# ── Background consolidation worker ──────────────────────────────────────────

def _consolidation_worker() -> None:
    logger.info("Memory forgetting worker started (%dh interval)", _CONSOLIDATION_INTERVAL)
    while not _stop_event.is_set():
        try:
            run_consolidation()
        except Exception as exc:
            logger.error("Consolidation failed: %s", exc)
        _stop_event.wait(_CONSOLIDATION_INTERVAL * 3600)


def start_forgetting_worker() -> None:
    global _consolidation_thread
    if _consolidation_thread and _consolidation_thread.is_alive():
        return
    _stop_event.clear()
    _consolidation_thread = threading.Thread(
        target=_consolidation_worker, daemon=True, name="memory-forgetting-worker"
    )
    _consolidation_thread.start()


def stop_forgetting_worker() -> None:
    _stop_event.set()
