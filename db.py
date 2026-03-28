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


# ── PINNED CHATS ──────────────────────────────────────────────────────────────

def pin_chat(cid: str, pinned: bool) -> None:
    try:
        _conn().execute("ALTER TABLE chats ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        _conn().commit()
    except Exception:
        pass   # column already exists
    _conn().execute("UPDATE chats SET pinned=? WHERE id=?", (1 if pinned else 0, cid))
    _conn().commit()
    _schedule_push()


def get_pinned_chats() -> list[str]:
    try:
        rows = _conn().execute("SELECT id FROM chats WHERE pinned=1 ORDER BY updated_at DESC").fetchall()
        return [r["id"] for r in rows]
    except Exception:
        return []


# ── FULL-TEXT SEARCH ──────────────────────────────────────────────────────────

def search_chats(query: str) -> list[dict]:
    """Simple case-insensitive search over chat titles and message content."""
    rows = _conn().execute(
        "SELECT id, title, updated_at, messages FROM chats ORDER BY updated_at DESC"
    ).fetchall()
    q    = query.lower()
    hits = []
    for row in rows:
        title = (row["title"] or "").lower()
        msgs  = row["messages"] or "[]"
        # Search in title
        if q in title:
            hits.append({"id": row["id"], "title": row["title"],
                         "updated_at": row["updated_at"], "match": "title"})
            continue
        # Search in message content
        try:
            import json as _j
            for m in _j.loads(msgs):
                content = m.get("content", "")
                if isinstance(content, str) and q in content.lower():
                    snippet = content[max(0, content.lower().find(q)-40):][:100]
                    hits.append({"id": row["id"], "title": row["title"],
                                 "updated_at": row["updated_at"],
                                 "match": "content", "snippet": snippet})
                    break
        except Exception:
            pass
    return hits[:20]


# ── CUSTOM PERSONAS ───────────────────────────────────────────────────────────

def save_custom_persona(pid: str, name: str, icon: str, description: str,
                        prompt_prefix: str, color: str,
                        temperature: float, tier: str) -> None:
    try:
        _conn().executescript("""
            CREATE TABLE IF NOT EXISTS custom_personas (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                icon         TEXT NOT NULL DEFAULT '🤖',
                description  TEXT NOT NULL DEFAULT '',
                prompt_prefix TEXT NOT NULL DEFAULT '',
                color        TEXT NOT NULL DEFAULT '#7c6af7',
                temperature  REAL NOT NULL DEFAULT 0.2,
                tier         TEXT NOT NULL DEFAULT 'medium'
            )
        """)
    except Exception:
        pass
    _conn().execute("""
        INSERT INTO custom_personas(id,name,icon,description,prompt_prefix,color,temperature,tier)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, icon=excluded.icon,
            description=excluded.description, prompt_prefix=excluded.prompt_prefix,
            color=excluded.color, temperature=excluded.temperature, tier=excluded.tier
    """, (pid, name, icon, description, prompt_prefix, color, temperature, tier))
    _conn().commit()
    _schedule_push()


def load_custom_personas() -> list[dict]:
    try:
        _conn().execute("CREATE TABLE IF NOT EXISTS custom_personas(id TEXT PRIMARY KEY, name TEXT, icon TEXT, description TEXT, prompt_prefix TEXT, color TEXT, temperature REAL, tier TEXT)")
        rows = _conn().execute("SELECT * FROM custom_personas").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def delete_custom_persona(pid: str) -> None:
    _conn().execute("DELETE FROM custom_personas WHERE id=?", (pid,))
    _conn().commit()
    _schedule_push()


# ── PINNED CHATS ──────────────────────────────────────────────────────────────

def init_pins_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS pinned_chats (
            chat_id    TEXT PRIMARY KEY,
            pinned_at  TEXT NOT NULL
        );
    """)
    _conn().commit()

def pin_chat(chat_id: str) -> None:
    from datetime import datetime
    _conn().execute(
        "INSERT OR IGNORE INTO pinned_chats(chat_id, pinned_at) VALUES(?,?)",
        (chat_id, datetime.utcnow().isoformat())
    )
    _conn().commit()
    _schedule_push()

def unpin_chat(chat_id: str) -> None:
    _conn().execute("DELETE FROM pinned_chats WHERE chat_id=?", (chat_id,))
    _conn().commit()
    _schedule_push()

def get_pinned_ids() -> set:
    rows = _conn().execute("SELECT chat_id FROM pinned_chats").fetchall()
    return {r["chat_id"] for r in rows}


# ── FULL-TEXT SEARCH ──────────────────────────────────────────────────────────

def search_chats(query: str) -> list[dict]:
    """Search chat titles and message content."""
    rows = _conn().execute(
        "SELECT id, title, created_at, updated_at, messages FROM chats"
    ).fetchall()
    query_lower = query.lower()
    results = []
    for r in rows:
        title = r["title"] or ""
        msgs  = json.loads(r["messages"]) if isinstance(r["messages"], str) else r["messages"]
        # Check title
        title_match = query_lower in title.lower()
        # Check message content
        content_match = False
        snippet = ""
        for m in msgs:
            content = m.get("content", "")
            if not isinstance(content, str): continue
            if query_lower in content.lower():
                content_match = True
                # Extract snippet around match
                idx = content.lower().find(query_lower)
                start = max(0, idx - 40)
                end   = min(len(content), idx + len(query) + 80)
                snippet = ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
                break
        if title_match or content_match:
            results.append({
                "id":         r["id"],
                "title":      title,
                "updated_at": r["updated_at"],
                "snippet":    snippet,
                "title_match": title_match,
            })
    # Sort: title matches first, then by date
    results.sort(key=lambda x: (not x["title_match"], x["updated_at"]), reverse=True)
    return results[:20]


# ── USER PREFERENCES ──────────────────────────────────────────────────────────

def save_pref(key: str, value: str) -> None:
    _conn().execute("CREATE TABLE IF NOT EXISTS user_prefs(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    _conn().execute(
        "INSERT INTO user_prefs(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value)
    )
    _conn().commit()
    _schedule_push()

def load_pref(key: str, default: str = "") -> str:
    try:
        _conn().execute("CREATE TABLE IF NOT EXISTS user_prefs(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = _conn().execute("SELECT value FROM user_prefs WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    except Exception:
        return default


# ── USAGE TRACKING ────────────────────────────────────────────────────────────

def init_usage_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS usage_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            provider    TEXT NOT NULL,
            model       TEXT NOT NULL,
            in_tokens   INTEGER NOT NULL DEFAULT 0,
            out_tokens  INTEGER NOT NULL DEFAULT 0,
            task_type   TEXT NOT NULL DEFAULT 'chat'
        );
        CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log(ts DESC);
    """)
    _conn().commit()


def log_usage(provider: str, model: str, in_tokens: int,
              out_tokens: int, task_type: str = "chat") -> None:
    import time as _t
    try:
        _conn().execute(
            "INSERT INTO usage_log(ts,provider,model,in_tokens,out_tokens,task_type) VALUES(?,?,?,?,?,?)",
            (_t.time(), provider, model, in_tokens, out_tokens, task_type)
        )
        _conn().commit()
    except Exception:
        pass   # never crash on usage logging


def get_usage_stats(days: int = 7) -> dict:
    import time as _t
    since = _t.time() - days * 86400
    rows  = _conn().execute(
        "SELECT provider, model, COUNT(*) as calls, SUM(in_tokens) as in_tok, SUM(out_tokens) as out_tok "
        "FROM usage_log WHERE ts >= ? GROUP BY provider, model ORDER BY calls DESC",
        (since,)
    ).fetchall()
    total_row = _conn().execute(
        "SELECT COUNT(*) as calls, SUM(in_tokens) as in_tok, SUM(out_tokens) as out_tok "
        "FROM usage_log WHERE ts >= ?", (since,)
    ).fetchone()
    return {
        "days":       days,
        "total":      dict(total_row) if total_row else {},
        "by_provider": [dict(r) for r in rows],
    }


def get_usage_daily(days: int = 14) -> list:
    import time as _t
    since = _t.time() - days * 86400
    rows  = _conn().execute(
        "SELECT date(ts,'unixepoch') as day, COUNT(*) as calls, "
        "SUM(in_tokens+out_tokens) as tokens "
        "FROM usage_log WHERE ts >= ? GROUP BY day ORDER BY day",
        (since,)
    ).fetchall()
    return [dict(r) for r in rows]
