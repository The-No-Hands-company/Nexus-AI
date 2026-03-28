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
