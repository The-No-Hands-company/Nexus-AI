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
from datetime import datetime, timezone
from pathlib import Path

try:
    from gist_backup import schedule_push as _schedule_push
except ImportError:
    def _schedule_push(): pass

DB_PATH = os.getenv("DB_PATH", "/tmp/nexus_ai.db")
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

        CREATE TABLE IF NOT EXISTS safety_audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            event_type  TEXT NOT NULL,
            session_id  TEXT,
            payload     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hitl_approvals (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL DEFAULT '',
            action      TEXT NOT NULL,
            signature   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            note        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_created ON memory(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_safety_audit_ts ON safety_audit(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_safety_audit_type ON safety_audit(event_type);
        CREATE INDEX IF NOT EXISTS idx_safety_audit_session ON safety_audit(session_id);
        CREATE INDEX IF NOT EXISTS idx_hitl_session ON hitl_approvals(session_id);
        CREATE INDEX IF NOT EXISTS idx_hitl_status ON hitl_approvals(status);

        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            task          TEXT NOT NULL,
            schedule      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'active',
            created_at    TEXT NOT NULL,
            interval_secs INTEGER,
            next_run      TEXT,
            last_run      TEXT,
            run_count     INTEGER NOT NULL DEFAULT 0,
            logs          TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_sched_status ON scheduled_jobs(status);
    """)
    c.commit()

def _ensure_safety_audit_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS safety_audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            event_type  TEXT NOT NULL,
            session_id  TEXT,
            payload     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_safety_audit_ts ON safety_audit(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_safety_audit_type ON safety_audit(event_type);
        CREATE INDEX IF NOT EXISTS idx_safety_audit_session ON safety_audit(session_id);
    """)
    _conn().commit()


def _ensure_hitl_approvals_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS hitl_approvals (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL DEFAULT '',
            action      TEXT NOT NULL,
            signature   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            note        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hitl_session ON hitl_approvals(session_id);
        CREATE INDEX IF NOT EXISTS idx_hitl_status ON hitl_approvals(status);
    """)
    _conn().commit()


def create_hitl_approval(
    approval_id: str,
    session_id: str,
    action: dict,
    signature: str,
    created_at: str,
    updated_at: str,
) -> None:
    _ensure_hitl_approvals_table()
    _conn().execute(
        """INSERT INTO hitl_approvals(id, session_id, action, signature, status, note, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'pending', '', ?, ?)""",
        (
            approval_id,
            session_id or "",
            json.dumps(action or {}, ensure_ascii=False),
            signature,
            created_at,
            updated_at,
        ),
    )
    _conn().commit()
    _schedule_push()


def list_hitl_approvals(session_id: str = "") -> list[dict]:
    _ensure_hitl_approvals_table()
    if session_id:
        rows = _conn().execute(
            """SELECT id, session_id, action, signature, status, note, created_at, updated_at
               FROM hitl_approvals
               WHERE session_id=?
               ORDER BY created_at DESC""",
            (session_id,),
        ).fetchall()
    else:
        rows = _conn().execute(
            """SELECT id, session_id, action, signature, status, note, created_at, updated_at
               FROM hitl_approvals
               ORDER BY created_at DESC"""
        ).fetchall()

    result: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["action"] = json.loads(item.get("action") or "{}")
        except Exception:
            item["action"] = {}
        result.append(item)
    return result


def load_hitl_approval(approval_id: str) -> dict | None:
    _ensure_hitl_approvals_table()
    row = _conn().execute(
        """SELECT id, session_id, action, signature, status, note, created_at, updated_at
           FROM hitl_approvals
           WHERE id=?""",
        (approval_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["action"] = json.loads(item.get("action") or "{}")
    except Exception:
        item["action"] = {}
    return item


def update_hitl_approval_decision(approval_id: str, status: str, note: str, updated_at: str) -> dict | None:
    _ensure_hitl_approvals_table()
    _conn().execute(
        "UPDATE hitl_approvals SET status=?, note=?, updated_at=? WHERE id=?",
        (status, note or "", updated_at, approval_id),
    )
    _conn().commit()
    _schedule_push()
    return load_hitl_approval(approval_id)


def consume_hitl_approval(approval_id: str, updated_at: str) -> None:
    _ensure_hitl_approvals_table()
    _conn().execute(
        "UPDATE hitl_approvals SET status='consumed', updated_at=? WHERE id=?",
        (updated_at, approval_id),
    )
    _conn().commit()
    _schedule_push()


def clear_hitl_approvals() -> None:
    _ensure_hitl_approvals_table()
    _conn().execute("DELETE FROM hitl_approvals")
    _conn().commit()


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


def prune_memory_by_age(older_than_ts: float, keep_min: int = 5) -> int:
    """Delete memory entries older than *older_than_ts* but always keep at least
    *keep_min* most-recent entries. Returns the number of deleted rows."""
    # Identify the IDs of the *keep_min* most-recent entries — never delete those.
    protected_ids = [
        r[0] for r in _conn().execute(
            "SELECT id FROM memory ORDER BY created_at DESC LIMIT ?", (keep_min,)
        ).fetchall()
    ]
    if protected_ids:
        placeholders = ",".join("?" * len(protected_ids))
        cur = _conn().execute(
            f"DELETE FROM memory WHERE created_at < ? AND id NOT IN ({placeholders})",
            (older_than_ts, *protected_ids),
        )
    else:
        cur = _conn().execute("DELETE FROM memory WHERE created_at < ?", (older_than_ts,))
    deleted = cur.rowcount
    _conn().commit()  # always commit to close the implicit write transaction
    if deleted:
        _schedule_push()
    return deleted


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


# ── SAFETY AUDIT LOG ─────────────────────────────────────────────────────────

def add_safety_audit_entry(event: dict) -> None:
    _ensure_safety_audit_table()
    payload = dict(event or {})
    ts = float(payload.get("ts") or datetime.now(timezone.utc).timestamp())
    event_type = str(payload.get("type") or "unknown")
    session_id = str(payload.get("session_id") or payload.get("session") or "")
    _conn().execute(
        "INSERT INTO safety_audit(ts, event_type, session_id, payload) VALUES(?,?,?,?)",
        (ts, event_type, session_id, json.dumps(payload, ensure_ascii=False)),
    )
    # Keep table bounded to avoid unbounded local growth.
    _conn().execute("""
        DELETE FROM safety_audit WHERE id NOT IN (
            SELECT id FROM safety_audit ORDER BY id DESC LIMIT 5000
        )
    """)
    _conn().commit()
    _schedule_push()


def load_safety_audit_entries(limit: int = 200, session_id: str = "", event_type: str = "") -> list[dict]:
    _ensure_safety_audit_table()
    where = []
    params: list = []
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if event_type:
        where.append("event_type = ?")
        params.append(event_type)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = _conn().execute(
        f"""
        SELECT payload FROM safety_audit
        {where_sql}
        ORDER BY ts DESC, id DESC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()

    entries: list[dict] = []
    for row in reversed(rows):
        try:
            entries.append(json.loads(row["payload"]))
        except Exception:
            continue
    return entries


def clear_safety_audit_entries() -> None:
    _ensure_safety_audit_table()
    _conn().execute("DELETE FROM safety_audit")
    _conn().commit()


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
    _conn().execute(
        "INSERT OR IGNORE INTO pinned_chats(chat_id, pinned_at) VALUES(?,?)",
        (chat_id, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
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


# ═══════════════════════════════════════════════════════════════════════════════
# USERS (simple username/password auth)
# ═══════════════════════════════════════════════════════════════════════════════

def init_users_table() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username    TEXT PRIMARY KEY,
            password    TEXT NOT NULL,    -- bcrypt hash
            created_at  TEXT NOT NULL,
            display_name TEXT
        );
    """)
    c.commit()


def create_user(username: str, password_hash: str, display_name: str = "") -> bool:
    """Returns True if created, False if username already exists."""
    try:
        _conn().execute(
            "INSERT INTO users(username, password, created_at, display_name) VALUES (?, ?, ?, ?)",
            (
                username,
                password_hash,
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                display_name or username,
            )
        )
        _conn().commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_user(username: str) -> dict | None:
    row = _conn().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        return None
    return dict(row)


def user_exists(username: str) -> bool:
    row = _conn().execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
    return row is not None


# Seed the table on import
try:
    init_users_table()
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK RESULTS
# ══════════════════════════════════════════════════════════════════════════════

def init_benchmark_table() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS benchmark_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            provider    TEXT NOT NULL,
            probe_name  TEXT NOT NULL,
            latency_ms  REAL NOT NULL,
            response_len INTEGER NOT NULL,
            ts          REAL NOT NULL
        );
    """)
    c.commit()


def save_benchmark_result(
    provider: str, probe_name: str, latency_ms: float,
    response_len: int, ts: float | None = None,
) -> None:
    import time as _t
    _conn().execute(
        "INSERT INTO benchmark_results(provider, probe_name, latency_ms, response_len, ts) "
        "VALUES (?, ?, ?, ?, ?)",
        (provider, probe_name, latency_ms, response_len, ts or _t.time()),
    )
    _conn().commit()


def load_benchmark_results(limit: int = 200) -> list[dict]:
    rows = _conn().execute(
        "SELECT provider, probe_name, latency_ms, response_len, ts "
        "FROM benchmark_results ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# Seed benchmark table on import
try:
    init_benchmark_table()
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# PER-MESSAGE FEEDBACK (training signal)
# ══════════════════════════════════════════════════════════════════════════════

def init_feedback_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS message_feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     TEXT NOT NULL,
            message_idx INTEGER NOT NULL,
            reaction    TEXT NOT NULL,   -- 'thumbs_up' | 'thumbs_down'
            provider    TEXT NOT NULL DEFAULT '',
            model       TEXT NOT NULL DEFAULT '',
            ts          REAL NOT NULL,
            UNIQUE (chat_id, message_idx)
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_ts ON message_feedback(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_reaction ON message_feedback(reaction);
    """)
    _conn().commit()


def save_feedback(
    chat_id: str,
    message_idx: int,
    reaction: str,
    provider: str = "",
    model: str = "",
) -> None:
    import time as _t
    _conn().execute(
        """INSERT INTO message_feedback(chat_id, message_idx, reaction, provider, model, ts)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(chat_id, message_idx) DO UPDATE SET
               reaction=excluded.reaction,
               provider=excluded.provider,
               model=excluded.model,
               ts=excluded.ts""",
        (chat_id, message_idx, reaction, provider, model, _t.time()),
    )
    _conn().commit()
    _schedule_push()


def load_feedback_export(limit: int = 5000) -> list[dict]:
    """Return all feedback rows ordered newest-first, for training data export."""
    rows = _conn().execute(
        """SELECT f.chat_id, f.message_idx, f.reaction, f.provider, f.model, f.ts,
                  c.messages
           FROM message_feedback f
           LEFT JOIN chats c ON c.id = f.chat_id
           ORDER BY f.ts DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    results = []
    for r in rows:
        entry: dict = {
            "chat_id":     r["chat_id"],
            "message_idx": r["message_idx"],
            "reaction":    r["reaction"],
            "provider":    r["provider"],
            "model":       r["model"],
            "ts":          r["ts"],
        }
        if r["messages"]:
            try:
                msgs = json.loads(r["messages"])
                idx  = r["message_idx"]
                if 0 <= idx < len(msgs):
                    entry["content"] = msgs[idx].get("content", "")
                # Try to include the user turn that prompted this response
                if idx > 0 and msgs[idx - 1].get("role") == "user":
                    entry["prompt"] = msgs[idx - 1].get("content", "")
            except Exception:
                pass
        results.append(entry)
    return results


def get_feedback_stats() -> dict:
    row = _conn().execute(
        """SELECT
               COUNT(*) as total,
               SUM(CASE WHEN reaction='thumbs_up'   THEN 1 ELSE 0 END) as up,
               SUM(CASE WHEN reaction='thumbs_down' THEN 1 ELSE 0 END) as down
           FROM message_feedback"""
    ).fetchone()
    return dict(row) if row else {"total": 0, "up": 0, "down": 0}


# Seed feedback table on import
try:
    init_feedback_table()
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# AGENT MARKETPLACE  (Sprint G)
# ══════════════════════════════════════════════════════════════════════════════

def init_marketplace_table() -> None:
    """Create the marketplace_agents table if it doesn't exist."""
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS marketplace_agents (
            id                  TEXT PRIMARY KEY,
            name                TEXT NOT NULL,
            icon                TEXT NOT NULL DEFAULT '🤖',
            description         TEXT NOT NULL DEFAULT '',
            system_prompt       TEXT NOT NULL DEFAULT '',
            keywords            TEXT NOT NULL DEFAULT '[]',  -- JSON array of str
            preferred_providers TEXT NOT NULL DEFAULT '[]',  -- JSON array of str
            temperature         REAL NOT NULL DEFAULT 0.7,
            tier                TEXT NOT NULL DEFAULT 'standard',
            source              TEXT NOT NULL DEFAULT 'imported', -- 'builtin'|'imported'
            created_at          REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_marketplace_source
            ON marketplace_agents(source);
    """)
    _conn().commit()


# ══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE REGISTRY + VERSIONED BLUEPRINTS
# ══════════════════════════════════════════════════════════════════════════════

def init_architecture_tables() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS architecture_blueprints (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            version      INTEGER NOT NULL,
            created_at   TEXT NOT NULL,
            notes        TEXT NOT NULL DEFAULT '',
            snapshot     TEXT NOT NULL,
            UNIQUE(name, version)
        );

        CREATE TABLE IF NOT EXISTS architecture_registry_nodes (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            blueprint_name     TEXT NOT NULL,
            blueprint_version  INTEGER NOT NULL,
            node_type          TEXT NOT NULL,
            node_id            TEXT NOT NULL,
            label              TEXT NOT NULL DEFAULT '',
            payload            TEXT NOT NULL,
            created_at         TEXT NOT NULL,
            UNIQUE(blueprint_name, blueprint_version, node_type, node_id)
        );

        CREATE TABLE IF NOT EXISTS architecture_registry_edges (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            blueprint_name     TEXT NOT NULL,
            blueprint_version  INTEGER NOT NULL,
            source_type        TEXT NOT NULL,
            source_id          TEXT NOT NULL,
            target_type        TEXT NOT NULL,
            target_id          TEXT NOT NULL,
            relation           TEXT NOT NULL,
            payload            TEXT NOT NULL,
            created_at         TEXT NOT NULL,
            UNIQUE(
                blueprint_name, blueprint_version,
                source_type, source_id,
                target_type, target_id,
                relation
            )
        );

        CREATE INDEX IF NOT EXISTS idx_arch_bp_name_ver
            ON architecture_blueprints(name, version DESC);
        CREATE INDEX IF NOT EXISTS idx_arch_nodes_bp
            ON architecture_registry_nodes(blueprint_name, blueprint_version);
        CREATE INDEX IF NOT EXISTS idx_arch_edges_bp
            ON architecture_registry_edges(blueprint_name, blueprint_version);
    """)
    _conn().commit()


def _arch_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_arch_nodes(snapshot: dict) -> list[tuple[str, str, str, dict]]:
    nodes: list[tuple[str, str, str, dict]] = []
    system = snapshot.get("system") or {}
    system_name = str(system.get("name") or "Nexus AI")
    nodes.append(("system", "system", system_name, system))

    for item in snapshot.get("foundation_models", []) or []:
        node_id = str(item.get("id") or "")
        if node_id:
            nodes.append(("foundation_model", node_id, str(item.get("label") or node_id), item))

    for item in snapshot.get("agent_layer", []) or []:
        node_id = str(item.get("id") or "")
        if node_id:
            nodes.append(("agent", node_id, str(item.get("name") or node_id), item))

    for item in snapshot.get("workflow_layer", []) or []:
        node_id = str(item.get("id") or "")
        if node_id:
            nodes.append(("workflow", node_id, str(item.get("name") or node_id), item))

    for item in snapshot.get("task_layer", []) or []:
        node_id = str(item.get("id") or "")
        if node_id:
            nodes.append(("tool", node_id, str(item.get("name") or node_id), item))

    return nodes


def _extract_arch_edges(snapshot: dict) -> list[tuple[str, str, str, str, str, dict]]:
    edges: list[tuple[str, str, str, str, str, dict]] = []
    system_name = str((snapshot.get("system") or {}).get("name") or "Nexus AI")

    for model in snapshot.get("foundation_models", []) or []:
        mid = str(model.get("id") or "")
        if mid:
            edges.append(("system", system_name, "foundation_model", mid, "contains_model", {}))

    for agent in snapshot.get("agent_layer", []) or []:
        aid = str(agent.get("id") or "")
        if not aid:
            continue
        edges.append(("system", system_name, "agent", aid, "contains_agent", {}))
        for mid in agent.get("model_ids", []) or []:
            edges.append(("agent", aid, "foundation_model", str(mid), "uses_model", {}))
        for wid in agent.get("workflow_ids", []) or []:
            edges.append(("agent", aid, "workflow", str(wid), "participates_in", {}))
        for tid in agent.get("tool_ids", []) or []:
            edges.append(("agent", aid, "tool", str(tid), "can_call_tool", {}))

    for workflow in snapshot.get("workflow_layer", []) or []:
        wid = str(workflow.get("id") or "")
        if not wid:
            continue
        edges.append(("system", system_name, "workflow", wid, "contains_workflow", {}))
        for aid in workflow.get("agent_ids", []) or []:
            edges.append(("workflow", wid, "agent", str(aid), "orchestrates_agent", {}))
        for tid in workflow.get("tool_ids", []) or []:
            edges.append(("workflow", wid, "tool", str(tid), "uses_tool", {}))

    return edges


def save_architecture_blueprint(name: str, snapshot: dict, notes: str = "") -> dict:
    init_architecture_tables()
    bp_name = (name or "default").strip() or "default"
    ts = _arch_now_iso()

    c = _conn()
    row = c.execute(
        "SELECT COALESCE(MAX(version), 0) as max_version FROM architecture_blueprints WHERE name=?",
        (bp_name,),
    ).fetchone()
    next_version = int((row["max_version"] if row else 0) or 0) + 1

    c.execute(
        "INSERT INTO architecture_blueprints(name, version, created_at, notes, snapshot) VALUES(?,?,?,?,?)",
        (bp_name, next_version, ts, notes or "", json.dumps(snapshot)),
    )

    nodes = _extract_arch_nodes(snapshot)
    for node_type, node_id, label, payload in nodes:
        c.execute(
            """INSERT OR REPLACE INTO architecture_registry_nodes(
                   blueprint_name, blueprint_version, node_type, node_id, label, payload, created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (bp_name, next_version, node_type, node_id, label, json.dumps(payload), ts),
        )

    edges = _extract_arch_edges(snapshot)
    for source_type, source_id, target_type, target_id, relation, payload in edges:
        c.execute(
            """INSERT OR REPLACE INTO architecture_registry_edges(
                   blueprint_name, blueprint_version,
                   source_type, source_id, target_type, target_id,
                   relation, payload, created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                bp_name,
                next_version,
                source_type,
                source_id,
                target_type,
                target_id,
                relation,
                json.dumps(payload or {}),
                ts,
            ),
        )

    c.commit()
    _schedule_push()
    return {
        "name": bp_name,
        "version": next_version,
        "created_at": ts,
        "notes": notes or "",
        "nodes": len(nodes),
        "edges": len(edges),
    }


def list_architecture_blueprints(name: str = "", limit: int = 50) -> list[dict]:
    init_architecture_tables()
    limit = max(1, min(int(limit or 50), 500))
    bp_name = (name or "").strip()
    if bp_name:
        rows = _conn().execute(
            """SELECT name, version, created_at, notes
               FROM architecture_blueprints
               WHERE name=?
               ORDER BY version DESC
               LIMIT ?""",
            (bp_name, limit),
        ).fetchall()
    else:
        rows = _conn().execute(
            """SELECT name, version, created_at, notes
               FROM architecture_blueprints
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_architecture_blueprint(name: str, version: int | None = None) -> dict | None:
    init_architecture_tables()
    bp_name = (name or "").strip()
    if not bp_name:
        return None

    if version is None:
        row = _conn().execute(
            """SELECT name, version, created_at, notes, snapshot
               FROM architecture_blueprints
               WHERE name=?
               ORDER BY version DESC
               LIMIT 1""",
            (bp_name,),
        ).fetchone()
    else:
        row = _conn().execute(
            """SELECT name, version, created_at, notes, snapshot
               FROM architecture_blueprints
               WHERE name=? AND version=?
               LIMIT 1""",
            (bp_name, int(version)),
        ).fetchone()

    if not row:
        return None
    data = dict(row)
    data["snapshot"] = json.loads(data["snapshot"])
    return data


def load_architecture_registry(name: str, version: int | None = None) -> dict | None:
    base = load_architecture_blueprint(name, version)
    if not base:
        return None

    bp_name = base["name"]
    bp_ver = int(base["version"])
    node_rows = _conn().execute(
        """SELECT node_type, node_id, label, payload
           FROM architecture_registry_nodes
           WHERE blueprint_name=? AND blueprint_version=?
           ORDER BY node_type, node_id""",
        (bp_name, bp_ver),
    ).fetchall()
    edge_rows = _conn().execute(
        """SELECT source_type, source_id, target_type, target_id, relation, payload
           FROM architecture_registry_edges
           WHERE blueprint_name=? AND blueprint_version=?
           ORDER BY source_type, source_id, relation, target_type, target_id""",
        (bp_name, bp_ver),
    ).fetchall()

    nodes = [
        {
            "type": r["node_type"],
            "id": r["node_id"],
            "label": r["label"],
            "payload": json.loads(r["payload"]),
        }
        for r in node_rows
    ]
    edges = [
        {
            "source": {"type": r["source_type"], "id": r["source_id"]},
            "target": {"type": r["target_type"], "id": r["target_id"]},
            "relation": r["relation"],
            "payload": json.loads(r["payload"]),
        }
        for r in edge_rows
    ]

    return {
        "name": bp_name,
        "version": bp_ver,
        "created_at": base["created_at"],
        "notes": base.get("notes", ""),
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "nodes": nodes,
        "edges": edges,
        "snapshot": base["snapshot"],
    }


# Seed architecture tables on import
try:
    init_architecture_tables()
except Exception:
    pass


def save_marketplace_agent(
    agent_id: str,
    name: str,
    icon: str,
    description: str,
    system_prompt: str,
    keywords: list,
    preferred_providers: list,
    temperature: float,
    tier: str,
    source: str = "imported",
) -> None:
    import time as _t
    _conn().execute(
        """INSERT INTO marketplace_agents
               (id, name, icon, description, system_prompt, keywords,
                preferred_providers, temperature, tier, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name,
               icon=excluded.icon,
               description=excluded.description,
               system_prompt=excluded.system_prompt,
               keywords=excluded.keywords,
               preferred_providers=excluded.preferred_providers,
               temperature=excluded.temperature,
               tier=excluded.tier,
               source=excluded.source""",
        (
            agent_id, name, icon, description, system_prompt,
            json.dumps(keywords), json.dumps(preferred_providers),
            temperature, tier, source, _t.time(),
        ),
    )
    _conn().commit()


def load_marketplace_agents(source: str | None = None) -> list[dict]:
    """Return all (or filtered) marketplace agents ordered by name."""
    if source:
        rows = _conn().execute(
            "SELECT * FROM marketplace_agents WHERE source=? ORDER BY name",
            (source,),
        ).fetchall()
    else:
        rows = _conn().execute(
            "SELECT * FROM marketplace_agents ORDER BY name"
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["keywords"]            = json.loads(d["keywords"])
        d["preferred_providers"] = json.loads(d["preferred_providers"])
        results.append(d)
    return results


def delete_marketplace_agent(agent_id: str) -> bool:
    """Delete an imported agent. Returns True if a row was deleted."""
    cur = _conn().execute(
        "DELETE FROM marketplace_agents WHERE id=? AND source='imported'",
        (agent_id,),
    )
    _conn().commit()
    return cur.rowcount > 0


# Seed marketplace table on import
try:
    init_marketplace_table()
except Exception:
    pass


# ── Self-review log ────────────────────────────────────────────────────────────

def init_self_review_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS self_review_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id        TEXT NOT NULL UNIQUE,
            traces_analyzed  INTEGER NOT NULL DEFAULT 0,
            insights         TEXT NOT NULL DEFAULT '[]',
            suggestions      TEXT NOT NULL DEFAULT '[]',
            provider         TEXT NOT NULL DEFAULT '',
            created_at       TEXT NOT NULL
        );
    """)
    _conn().commit()


def save_self_review(
    review_id: str,
    traces_analyzed: int,
    insights: list,
    suggestions: list,
    provider: str = "",
) -> None:
    import time as _t
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    import json as _json
    _conn().execute(
        "INSERT OR REPLACE INTO self_review_log "
        "(review_id, traces_analyzed, insights, suggestions, provider, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (review_id, traces_analyzed,
         _json.dumps(insights), _json.dumps(suggestions),
         provider, now),
    )
    _conn().commit()


def list_self_reviews(limit: int = 20) -> list[dict]:
    import json as _json
    rows = _conn().execute(
        "SELECT * FROM self_review_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["insights"]    = _json.loads(d.get("insights") or "[]")
        d["suggestions"] = _json.loads(d.get("suggestions") or "[]")
        results.append(d)
    return results


# Seed self-review table on import
try:
    init_self_review_table()
except Exception:
    pass


# ── SCHEDULED JOBS ────────────────────────────────────────────────────────────

def _ensure_scheduled_jobs_table() -> None:
    _conn().executescript("""
        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            task          TEXT NOT NULL,
            schedule      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'active',
            created_at    TEXT NOT NULL,
            interval_secs INTEGER,
            next_run      TEXT,
            last_run      TEXT,
            run_count     INTEGER NOT NULL DEFAULT 0,
            logs          TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_sched_status ON scheduled_jobs(status);
    """)
    _conn().commit()


def upsert_scheduled_job(job: dict) -> None:
    """Persist (insert or update) a scheduled job row."""
    _ensure_scheduled_jobs_table()
    _conn().execute(
        """
        INSERT INTO scheduled_jobs
            (id, name, task, schedule, status, created_at, interval_secs,
             next_run, last_run, run_count, logs)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, task=excluded.task, schedule=excluded.schedule,
            status=excluded.status, interval_secs=excluded.interval_secs,
            next_run=excluded.next_run, last_run=excluded.last_run,
            run_count=excluded.run_count, logs=excluded.logs
        """,
        (
            job["id"],
            job["name"],
            job["task"],
            job["schedule"],
            job["status"],
            job["created_at"],
            job.get("interval_secs"),
            job.get("next_run"),
            job.get("last_run"),
            job.get("run_count", 0),
            json.dumps(job.get("logs") or []),
        ),
    )
    _conn().commit()


def load_scheduled_jobs() -> list[dict]:
    """Return all persisted scheduled jobs (any status)."""
    _ensure_scheduled_jobs_table()
    rows = _conn().execute(
        "SELECT id,name,task,schedule,status,created_at,interval_secs,"
        "next_run,last_run,run_count,logs FROM scheduled_jobs"
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["logs"] = json.loads(d.get("logs") or "[]")
        except Exception:
            d["logs"] = []
        result.append(d)
    return result


def delete_scheduled_job(job_id: str) -> None:
    """Remove a scheduled job from the DB."""
    _ensure_scheduled_jobs_table()
    _conn().execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
    _conn().commit()


def clear_scheduled_jobs() -> None:
    """Delete all scheduled jobs — used in tests only."""
    _ensure_scheduled_jobs_table()
    _conn().execute("DELETE FROM scheduled_jobs")
    _conn().commit()
