"""
SQLite persistence layer.
Stores: sessions, chats, shares, memory entries.
All in-memory dicts in main.py are seeded from here on startup
and written through on every mutation.
"""
import os
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

try:
    from gist_backup import schedule_push as _schedule_push
except ImportError:
    def _schedule_push(): pass

DB_PATH = os.getenv("DB_PATH", "/tmp/claude_alt.db")
_local  = threading.local()


def _conn() -> sqlite3.Connection:
    """Thread-local connection with WAL mode for concurrent reads."""
    if not hasattr(_local, "conn") or _local.conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    """Create tables if they don't exist."""
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            messages    TEXT NOT NULL   -- JSON array
        );

        CREATE TABLE IF NOT EXISTS shares (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            messages    TEXT NOT NULL   -- JSON array
        );

        CREATE TABLE IF NOT EXISTS memory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  REAL NOT NULL,   -- unix timestamp
            summary     TEXT NOT NULL,
            tags        TEXT NOT NULL    -- JSON array
        );

        CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_created ON memory(created_at DESC);
    """)
    c.commit()


# ── CHATS ─────────────────────────────────────────────────────────────────────

def save_chat(cid: str, title: str, created_at: str,
              updated_at: str, messages: list) -> None:
    _conn().execute(
        """INSERT INTO chats(id, title, created_at, updated_at, messages)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               title=excluded.title,
               updated_at=excluded.updated_at,
               messages=excluded.messages""",
        (cid, title[:80], created_at, updated_at, json.dumps(messages))
    )
    _conn().commit()
    _schedule_push()


def load_chats() -> list[dict]:
    rows = _conn().execute(
        "SELECT id, title, created_at, updated_at, messages FROM chats ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def load_chat(cid: str) -> dict | None:
    row = _conn().execute(
        "SELECT id, title, created_at, updated_at, messages FROM chats WHERE id=?", (cid,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["messages"] = json.loads(d["messages"])
    return d


def delete_chat(cid: str) -> None:
    _conn().execute("DELETE FROM chats WHERE id=?", (cid,))
    _conn().commit()


# ── SHARES ────────────────────────────────────────────────────────────────────

def save_share(sid: str, title: str, created_at: str, messages: list) -> None:
    _conn().execute(
        "INSERT OR IGNORE INTO shares(id, title, created_at, messages) VALUES(?,?,?,?)",
        (sid, title, created_at, json.dumps(messages))
    )
    _conn().commit()
    _schedule_push()


def load_share(sid: str) -> dict | None:
    row = _conn().execute(
        "SELECT id, title, created_at, messages FROM shares WHERE id=?", (sid,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["messages"] = json.loads(d["messages"])
    return d


# ── MEMORY ────────────────────────────────────────────────────────────────────

def add_memory_entry(summary: str, tags: list, ts: float) -> None:
    _conn().execute(
        "INSERT INTO memory(created_at, summary, tags) VALUES(?,?,?)",
        (ts, summary, json.dumps(tags))
    )
    # Keep only last 20
    _conn().execute("""
        DELETE FROM memory WHERE id NOT IN (
            SELECT id FROM memory ORDER BY created_at DESC LIMIT 20
        )
    """)
    _conn().commit()
    _schedule_push()


def load_memory_entries(limit: int = 20) -> list[dict]:
    rows = _conn().execute(
        "SELECT id, created_at, summary, tags FROM memory ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d["tags"])
        result.append(d)
    return result


def delete_all_memory() -> None:
    _conn().execute("DELETE FROM memory")
    _conn().commit()
    _schedule_push()


# ── PROJECTS ──────────────────────────────────────────────────────────────────

def init_projects_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            instructions TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            color        TEXT NOT NULL DEFAULT '#7c6af7'
        );
        CREATE TABLE IF NOT EXISTS project_chats (
            project_id  TEXT NOT NULL,
            chat_id     TEXT NOT NULL,
            PRIMARY KEY (project_id, chat_id),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (chat_id)    REFERENCES chats(id)    ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_pc_project ON project_chats(project_id);
    """)
    _conn().commit()


def save_project(pid: str, name: str, instructions: str,
                 color: str, created_at: str, updated_at: str) -> None:
    _conn().execute("""
        INSERT INTO projects(id, name, instructions, color, created_at, updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, instructions=excluded.instructions,
            color=excluded.color, updated_at=excluded.updated_at
    """, (pid, name[:80], instructions, color, created_at, updated_at))
    _conn().commit()
    _schedule_push()


def load_projects() -> list[dict]:
    rows = _conn().execute(
        "SELECT id,name,instructions,color,created_at,updated_at FROM projects ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_project(pid: str) -> None:
    _conn().execute("DELETE FROM projects WHERE id=?", (pid,))
    _conn().commit()
    _schedule_push()


def assign_chat_to_project(project_id: str, chat_id: str) -> None:
    _conn().execute(
        "INSERT OR IGNORE INTO project_chats(project_id, chat_id) VALUES(?,?)",
        (project_id, chat_id)
    )
    _conn().commit()
    _schedule_push()


def get_project_chats(project_id: str) -> list[str]:
    rows = _conn().execute(
        "SELECT chat_id FROM project_chats WHERE project_id=?", (project_id,)
    ).fetchall()
    return [r["chat_id"] for r in rows]


# ── CUSTOM INSTRUCTIONS ────────────────────────────────────────────────────────

def save_custom_instructions(instructions: str) -> None:
    """Single-row user preferences table."""
    _conn().execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    _conn().execute(
        "INSERT INTO user_prefs(key,value) VALUES('custom_instructions',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (instructions,)
    )
    _conn().commit()
    _schedule_push()


def load_custom_instructions() -> str:
    try:
        _conn().execute("CREATE TABLE IF NOT EXISTS user_prefs(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = _conn().execute(
            "SELECT value FROM user_prefs WHERE key='custom_instructions'"
        ).fetchone()
        return row["value"] if row else ""
    except Exception:
        return ""


# ── MEMORY CRUD ────────────────────────────────────────────────────────────────

def update_memory_entry(entry_id: int, summary: str) -> None:
    _conn().execute("UPDATE memory SET summary=? WHERE id=?", (summary, entry_id))
    _conn().commit()
    _schedule_push()


def delete_memory_entry(entry_id: int) -> None:
    _conn().execute("DELETE FROM memory WHERE id=?", (entry_id,))
    _conn().commit()
    _schedule_push()
