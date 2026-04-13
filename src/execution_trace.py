"""
Execution Trace — SQLite-backed checkpoint persistence for replayable agent sessions.

Tables:
  trace_checkpoints (id INTEGER PK, trace_id TEXT, step_idx INT,
                     task TEXT, history TEXT, events TEXT, created_at TEXT)

Public API:
  init_trace_tables()
  save_checkpoint(trace_id, step_idx, task, history, events)
  load_checkpoints(trace_id) -> list[dict]
  get_latest_checkpoint(trace_id) -> dict | None
  list_traces(limit) -> list[dict]
  delete_trace(trace_id) -> bool
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "/tmp/nexus_ai.db")
_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "trace_conn") or _local.trace_conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.trace_conn = conn
    return _local.trace_conn


def init_trace_tables() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS trace_checkpoints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id    TEXT NOT NULL,
            step_idx    INTEGER NOT NULL DEFAULT 0,
            task        TEXT NOT NULL DEFAULT '',
            history     TEXT NOT NULL DEFAULT '[]',
            events      TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trace_checkpoints_trace_id
            ON trace_checkpoints(trace_id);
    """)
    c.commit()


# Initialise on import
init_trace_tables()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def save_checkpoint(
    trace_id: str,
    step_idx: int,
    task: str,
    history: list,
    events: list,
) -> None:
    """Persist a checkpoint for the given trace_id."""
    if not trace_id:
        return
    c = _conn()
    c.execute(
        "INSERT INTO trace_checkpoints (trace_id, step_idx, task, history, events, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            trace_id,
            step_idx,
            task or "",
            json.dumps(history or [], default=str),
            json.dumps(events or [], default=str),
            _now(),
        ),
    )
    c.commit()


def load_checkpoints(trace_id: str) -> list[dict]:
    """Return all checkpoints for a trace, ordered by step_idx."""
    if not trace_id:
        return []
    c = _conn()
    rows = c.execute(
        "SELECT * FROM trace_checkpoints WHERE trace_id=? ORDER BY step_idx ASC",
        (trace_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["history"] = json.loads(d.get("history") or "[]")
        d["events"] = json.loads(d.get("events") or "[]")
        result.append(d)
    return result


def get_latest_checkpoint(trace_id: str) -> dict | None:
    """Return the most recent checkpoint for a trace, or None."""
    if not trace_id:
        return None
    c = _conn()
    row = c.execute(
        "SELECT * FROM trace_checkpoints WHERE trace_id=? ORDER BY step_idx DESC LIMIT 1",
        (trace_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["history"] = json.loads(d.get("history") or "[]")
    d["events"] = json.loads(d.get("events") or "[]")
    return d


def list_traces(limit: int = 50) -> list[dict]:
    """Return a summary of all traces (latest checkpoint per trace_id)."""
    c = _conn()
    rows = c.execute(
        """
        SELECT trace_id,
               MAX(step_idx)    AS steps,
               MIN(created_at)  AS started_at,
               MAX(created_at)  AS last_active,
               task
        FROM trace_checkpoints
        GROUP BY trace_id
        ORDER BY last_active DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_trace(trace_id: str) -> bool:
    """Delete all checkpoints for a trace."""
    if not trace_id:
        return False
    c = _conn()
    result = c.execute("DELETE FROM trace_checkpoints WHERE trace_id=?", (trace_id,))
    c.commit()
    return result.rowcount > 0
