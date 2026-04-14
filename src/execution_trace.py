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


# ── File diff persistence ──────────────────────────────────────────────────────

def init_file_diff_table() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS file_diffs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id    TEXT NOT NULL DEFAULT '',
            file_path   TEXT NOT NULL DEFAULT '',
            before_text TEXT NOT NULL DEFAULT '',
            after_text  TEXT NOT NULL DEFAULT '',
            diff_text   TEXT NOT NULL DEFAULT '',
            additions   INTEGER NOT NULL DEFAULT 0,
            deletions   INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_file_diffs_trace_id
            ON file_diffs(trace_id);
    """)
    c.commit()


def _compute_unified_diff(before: str, after: str, filename: str = "file") -> str:
    import difflib
    orig_lines = before.splitlines(keepends=True)
    mod_lines  = after.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        orig_lines, mod_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="",
    ))
    return "\n".join(diff)


def save_file_diff(
    trace_id: str,
    file_path: str,
    before: str,
    after: str,
) -> dict:
    """Compute and persist a before/after diff for a file edit.

    Returns the stored record as a dict (without the full text blobs).
    """
    filename = Path(file_path).name if file_path else "file"
    diff_text = _compute_unified_diff(before, after, filename)
    additions = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
    now = _now()
    c = _conn()
    c.execute(
        "INSERT INTO file_diffs "
        "(trace_id, file_path, before_text, after_text, diff_text, additions, deletions, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (trace_id or "", file_path or "", before or "", after or "",
         diff_text, additions, deletions, now),
    )
    c.commit()
    row_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {
        "id": row_id,
        "trace_id": trace_id,
        "file_path": file_path,
        "additions": additions,
        "deletions": deletions,
        "created_at": now,
    }


def get_file_diffs(trace_id: str = "", limit: int = 50) -> list[dict]:
    """Return file diffs, optionally filtered by trace_id (most recent first)."""
    c = _conn()
    if trace_id:
        rows = c.execute(
            "SELECT id, trace_id, file_path, additions, deletions, created_at "
            "FROM file_diffs WHERE trace_id=? ORDER BY id DESC LIMIT ?",
            (trace_id, limit),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT id, trace_id, file_path, additions, deletions, created_at "
            "FROM file_diffs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_file_diff_detail(diff_id: int) -> dict | None:
    """Return full diff record including before/after text and unified diff."""
    c = _conn()
    row = c.execute(
        "SELECT * FROM file_diffs WHERE id=?", (diff_id,)
    ).fetchone()
    return dict(row) if row else None


# Auto-initialise
try:
    init_file_diff_table()
except Exception:
    pass
