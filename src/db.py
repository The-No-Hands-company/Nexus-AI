"""
Nexus AI Database Abstraction Layer.
Supports SQLite (default) and PostgreSQL (via DATABASE_URL).
"""
import os
import json
import time
import uuid
import threading
import sqlite3
import contextlib
import hashlib
from typing import List, Dict, Optional, Any, Set
from datetime import datetime, timezone
from pathlib import Path
from abc import ABC, abstractmethod

# ── INTERFACE ────────────────────────────────────────────────────────────────

class DatabaseBackend(ABC):
    @abstractmethod
    def init_db(self): pass

    @abstractmethod
    def save_chat(self, cid: str, title: str, created_at: str, updated_at: str, messages: list): pass

    @abstractmethod
    def load_chats(self) -> list[dict]: pass

    @abstractmethod
    def load_chat(self, cid: str) -> dict | None: pass

    @abstractmethod
    def delete_chat(self, cid: str): pass

    @abstractmethod
    def save_share(self, sid: str, title: str, created_at: str, messages: list): pass

    @abstractmethod
    def load_share(self, sid: str) -> dict | None: pass

    @abstractmethod
    def add_memory_entry(self, summary: str, tags: list, ts: float): pass

    @abstractmethod
    def load_memory_entries(self, limit: int = 20) -> list[dict]: pass

    @abstractmethod
    def delete_all_memory(self): pass

    @abstractmethod
    def prune_memory_by_age(self, older_than_ts: float, keep_min: int = 5) -> int: pass

    @abstractmethod
    def init_projects_table(self): pass

    @abstractmethod
    def save_project(self, pid: str, name: str, instructions: str, color: str, created_at: str, updated_at: str): pass

    @abstractmethod
    def load_projects(self) -> list[dict]: pass

    @abstractmethod
    def delete_project(self, pid: str): pass

    @abstractmethod
    def assign_chat_to_project(self, project_id: str, chat_id: str): pass

    @abstractmethod
    def get_project_chats(self, project_id: str) -> list[str]: pass

    @abstractmethod
    def save_pref(self, key: str, value: str): pass

    @abstractmethod
    def load_pref(self, key: str, default: str = "") -> str: pass

    @abstractmethod
    def log_usage(
        self,
        provider: str,
        model: str,
        in_tokens: int,
        out_tokens: int,
        task_type: str = "chat",
        username: str = "",
        cost_usd: float = 0.0,
    ): pass

    @abstractmethod
    def get_usage_stats(self, days: int = 7) -> dict: pass

    @abstractmethod
    def create_user(self, username: str, password_hash: str, display_name: str = "", role: str = "user") -> bool: pass

    @abstractmethod
    def get_user(self, username: str) -> dict | None: pass

    @abstractmethod
    def user_exists(self, username: str) -> bool: pass

    @abstractmethod
    def save_feedback(self, chat_id: str, message_idx: int, reaction: str, provider: str = "", model: str = ""): pass

    @abstractmethod
    def list_users(self) -> list[dict]: pass

    @abstractmethod
    def update_user_role(self, username: str, role: str) -> bool: pass

    @abstractmethod
    def count_users(self) -> int: pass

    @abstractmethod
    def update_user_email(self, username: str, email: str, verified: bool = False) -> bool: pass

    @abstractmethod
    def get_user_by_email(self, username: str) -> dict | None: pass

    # ── API keys ──────────────────────────────────────────────────────────────
    @abstractmethod
    def create_api_key(self, key_id: str, username: str, key_hash: str, key_prefix: str,
                       name: str, scopes: list[str], created_at: float) -> bool: pass

    @abstractmethod
    def list_api_keys(self, username: str) -> list[dict]: pass

    @abstractmethod
    def get_api_key_by_hash(self, key_hash: str) -> dict | None: pass

    @abstractmethod
    def revoke_api_key(self, key_id: str, username: str) -> bool: pass

    @abstractmethod
    def touch_api_key(self, key_id: str, ts: float) -> None: pass

    # ── OAuth ─────────────────────────────────────────────────────────────────
    @abstractmethod
    def get_or_create_oauth_user(self, provider: str, provider_id: str,
                                  email: str, display_name: str) -> dict: pass

# ── SQLITE BACKEND ────────────────────────────────────────────────────────────

class SQLiteBackend(DatabaseBackend):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def init_db(self):
        c = self._conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS chats (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                messages    TEXT NOT NULL,
                pinned      INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS shares (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                messages    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  REAL NOT NULL,
                summary     TEXT NOT NULL,
                tags        TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_prefs (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                provider    TEXT NOT NULL,
                model       TEXT NOT NULL,
                in_tokens   INTEGER NOT NULL DEFAULT 0,
                out_tokens  INTEGER NOT NULL DEFAULT 0,
                task_type   TEXT NOT NULL DEFAULT 'chat',
                username    TEXT NOT NULL DEFAULT '',
                cost_usd    REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS users (
                username    TEXT PRIMARY KEY,
                password    TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                display_name TEXT,
                role        TEXT NOT NULL DEFAULT 'user'
            );
            CREATE TABLE IF NOT EXISTS message_feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     TEXT NOT NULL,
                message_idx INTEGER NOT NULL,
                reaction    TEXT NOT NULL,
                provider    TEXT NOT NULL DEFAULT '',
                model       TEXT NOT NULL DEFAULT '',
                ts          REAL NOT NULL,
                UNIQUE (chat_id, message_idx)
            );
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS auth_api_keys (
                id           TEXT PRIMARY KEY,
                username     TEXT NOT NULL,
                key_hash     TEXT NOT NULL UNIQUE,
                key_prefix   TEXT NOT NULL,
                name         TEXT NOT NULL,
                scopes       TEXT NOT NULL,
                created_at   REAL NOT NULL,
                last_used_at REAL,
                revoked_at   REAL
            );
            CREATE TABLE IF NOT EXISTS oauth_accounts (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                provider    TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                UNIQUE(provider, provider_id)
            );
            CREATE TABLE IF NOT EXISTS fine_tuning_jobs (
                id               TEXT PRIMARY KEY,
                created_at       INTEGER NOT NULL,
                finished_at      INTEGER,
                model            TEXT NOT NULL,
                fine_tuned_model TEXT,
                organization_id  TEXT NOT NULL,
                status           TEXT NOT NULL,
                training_file    TEXT NOT NULL,
                validation_file  TEXT,
                hyperparameters  TEXT NOT NULL,
                trained_tokens   INTEGER,
                error            TEXT,
                result_files     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fine_tuning_job_events (
                id               TEXT PRIMARY KEY,
                job_id           TEXT NOT NULL,
                created_at       INTEGER NOT NULL,
                level            TEXT NOT NULL DEFAULT 'info',
                message          TEXT NOT NULL,
                data             TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS execution_traces (
                trace_id    TEXT PRIMARY KEY,
                events      TEXT NOT NULL DEFAULT '[]',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS autonomy_traces (
                trace_id    TEXT PRIMARY KEY,
                data        TEXT NOT NULL DEFAULT '{}',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_shared_memory (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL DEFAULT 'null',
                updated_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_queue_jobs (
                task_id       TEXT PRIMARY KEY,
                description   TEXT NOT NULL,
                priority      INTEGER NOT NULL DEFAULT 5,
                dependencies  TEXT NOT NULL DEFAULT '[]',
                metadata      TEXT NOT NULL DEFAULT '{}',
                schedule_cron TEXT NOT NULL DEFAULT '',
                status        TEXT NOT NULL DEFAULT 'pending',
                result        TEXT NOT NULL DEFAULT '',
                error         TEXT NOT NULL DEFAULT '',
                created_at    REAL NOT NULL,
                started_at    REAL,
                finished_at   REAL
            );
            CREATE TABLE IF NOT EXISTS ft_training_samples (
                id          TEXT PRIMARY KEY,
                created_at  REAL NOT NULL,
                task        TEXT NOT NULL,
                result      TEXT NOT NULL,
                quality     REAL NOT NULL DEFAULT 0.7,
                lessons     TEXT NOT NULL DEFAULT '[]',
                source      TEXT NOT NULL DEFAULT 'reflection'
            );
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS orgs (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                owner          TEXT NOT NULL,
                plan           TEXT NOT NULL DEFAULT 'free',
                metadata       TEXT NOT NULL DEFAULT '{}',
                tokens_per_day INTEGER NOT NULL DEFAULT 0,
                spend_cap_usd  REAL NOT NULL DEFAULT 0,
                created_at     REAL NOT NULL,
                updated_at     REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS org_members (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id     TEXT NOT NULL,
                username   TEXT NOT NULL,
                role       TEXT NOT NULL DEFAULT 'member',
                joined_at  REAL NOT NULL,
                UNIQUE(org_id, username)
            );
            CREATE TABLE IF NOT EXISTS org_invites (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id      TEXT NOT NULL,
                token       TEXT NOT NULL UNIQUE,
                invited_by  TEXT NOT NULL,
                email       TEXT NOT NULL DEFAULT '',
                role        TEXT NOT NULL DEFAULT 'member',
                expires_at  REAL NOT NULL,
                used        INTEGER NOT NULL DEFAULT 0,
                used_by     TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mfa_secrets (
                username    TEXT PRIMARY KEY,
                secret      TEXT NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL,
                code_hash   TEXT NOT NULL,
                used        INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL,
                ip_address  TEXT NOT NULL DEFAULT '',
                success     INTEGER NOT NULL DEFAULT 0,
                ts          REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trusted_devices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL,
                device_hash TEXT NOT NULL,
                label       TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL,
                last_seen   REAL NOT NULL,
                UNIQUE(username, device_hash)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                actor       TEXT NOT NULL,
                action      TEXT NOT NULL,
                resource    TEXT NOT NULL DEFAULT '',
                result      TEXT NOT NULL DEFAULT 'ok',
                metadata    TEXT NOT NULL DEFAULT '{}',
                request_id  TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS feature_flags (
                name                TEXT PRIMARY KEY,
                enabled             INTEGER NOT NULL DEFAULT 0,
                description         TEXT NOT NULL DEFAULT '',
                rollout_percentage  INTEGER NOT NULL DEFAULT 0,
                user_overrides      TEXT NOT NULL DEFAULT '{}',
                org_overrides       TEXT NOT NULL DEFAULT '{}',
                value               TEXT NOT NULL DEFAULT '',
                updated_at          REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS backup_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL NOT NULL,
                type       TEXT NOT NULL DEFAULT 'local',
                status     TEXT NOT NULL DEFAULT 'ok',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                location   TEXT NOT NULL DEFAULT '',
                checksum   TEXT NOT NULL DEFAULT '',
                error      TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS org_api_keys (
                id           TEXT PRIMARY KEY,
                org_id       TEXT NOT NULL,
                created_by   TEXT NOT NULL,
                key_hash     TEXT NOT NULL UNIQUE,
                key_prefix   TEXT NOT NULL,
                name         TEXT NOT NULL,
                scopes       TEXT NOT NULL DEFAULT '[]',
                created_at   REAL NOT NULL,
                last_used_at REAL,
                revoked_at   REAL
            );
            CREATE TABLE IF NOT EXISTS webauthn_credentials (
                id              TEXT PRIMARY KEY,
                username        TEXT NOT NULL,
                credential_id   TEXT NOT NULL UNIQUE,
                public_key      TEXT NOT NULL,
                sign_count      INTEGER NOT NULL DEFAULT 0,
                device_name     TEXT NOT NULL DEFAULT '',
                created_at      REAL NOT NULL,
                last_used_at    REAL
            );
            CREATE TABLE IF NOT EXISTS saml_sessions (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL DEFAULT '',
                provider    TEXT NOT NULL DEFAULT '',
                relay_state TEXT NOT NULL DEFAULT '',
                nameid      TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL,
                expires_at  REAL NOT NULL
            );
        """)
        # ── Budget / attribution / department / safety audit tables ──────────
        c.executescript("""
            CREATE TABLE IF NOT EXISTS team_budgets (
                team_id              TEXT PRIMARY KEY,
                monthly_limit_usd    REAL NOT NULL DEFAULT 0,
                daily_limit_usd      REAL NOT NULL DEFAULT 0,
                alert_threshold_pct  REAL NOT NULL DEFAULT 80,
                updated_at           TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS team_spending (
                team_id       TEXT PRIMARY KEY,
                today_usd     REAL NOT NULL DEFAULT 0,
                month_usd     REAL NOT NULL DEFAULT 0,
                total_usd     REAL NOT NULL DEFAULT 0,
                reset_date    TEXT NOT NULL DEFAULT '',
                reset_month   TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS budget_alerts (
                id          TEXT PRIMARY KEY,
                team_id     TEXT NOT NULL,
                alert_type  TEXT NOT NULL DEFAULT 'monthly_budget_threshold',
                utilization REAL NOT NULL DEFAULT 0,
                threshold   REAL NOT NULL DEFAULT 0,
                ts          TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attribution_log (
                id         TEXT PRIMARY KEY,
                ts         TEXT NOT NULL,
                team_id    TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                username   TEXT NOT NULL DEFAULT '',
                cost_usd   REAL NOT NULL DEFAULT 0,
                tokens     INTEGER NOT NULL DEFAULT 0,
                model      TEXT NOT NULL DEFAULT '',
                endpoint   TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS department_quotas (
                department          TEXT PRIMARY KEY,
                daily_tokens        INTEGER NOT NULL DEFAULT 0,
                monthly_cost_cap    REAL NOT NULL DEFAULT 0,
                updated_at          TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS department_usage (
                department      TEXT PRIMARY KEY,
                tokens_today    INTEGER NOT NULL DEFAULT 0,
                cost_this_month REAL NOT NULL DEFAULT 0,
                users           INTEGER NOT NULL DEFAULT 0,
                reset_date      TEXT NOT NULL DEFAULT '',
                reset_month     TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS safety_audit_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                session_id  TEXT NOT NULL DEFAULT '',
                username    TEXT NOT NULL DEFAULT '',
                severity    TEXT NOT NULL DEFAULT 'info',
                details     TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_safety_audit_ts
                ON safety_audit_events (ts);
            CREATE INDEX IF NOT EXISTS idx_safety_audit_event_type
                ON safety_audit_events (event_type);
            CREATE INDEX IF NOT EXISTS idx_attribution_log_ts
                ON attribution_log (ts);
            CREATE INDEX IF NOT EXISTS idx_attribution_log_team
                ON attribution_log (team_id);
            CREATE INDEX IF NOT EXISTS idx_budget_alerts_team
                ON budget_alerts (team_id);
        """)
        c.commit()
        # Migrate existing databases
        for col_sql in [
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'",
            "ALTER TABLE users ADD COLUMN email TEXT",
            "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE chats ADD COLUMN username TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE usage_log ADD COLUMN username TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE usage_log ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0",
        ]:
            try:
                c.execute(col_sql)
                c.commit()
            except Exception:
                pass

    def save_chat(self, cid: str, title: str, created_at: str, updated_at: str, messages: list):
        self._conn().execute(
            """INSERT INTO chats(id, title, created_at, updated_at, messages)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title,
                   updated_at=excluded.updated_at,
                   messages=excluded.messages""",
            (cid, title[:80], created_at, updated_at, json.dumps(messages))
        )
        self._conn().commit()

    def load_chats(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id, title, created_at, updated_at, messages FROM chats ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def load_chat(self, cid: str) -> dict | None:
        row = self._conn().execute(
            "SELECT id, title, created_at, updated_at, messages FROM chats WHERE id=?", (cid,)
        ).fetchone()
        if not row: return None
        d = dict(row)
        d["messages"] = json.loads(d["messages"])
        return d

    def delete_chat(self, cid: str):
        self._conn().execute("DELETE FROM chats WHERE id=?", (cid,))
        self._conn().commit()

    def save_share(self, sid: str, title: str, created_at: str, messages: list):
        self._conn().execute(
            "INSERT OR IGNORE INTO shares(id, title, created_at, messages) VALUES(?,?,?,?)",
            (sid, title, created_at, json.dumps(messages))
        )
        self._conn().commit()

    def load_share(self, sid: str) -> dict | None:
        row = self._conn().execute(
            "SELECT id, title, created_at, messages FROM shares WHERE id=?", (sid,)
        ).fetchone()
        if not row: return None
        d = dict(row)
        d["messages"] = json.loads(d["messages"])
        return d

    def add_memory_entry(self, summary: str, tags: list, ts: float):
        self._conn().execute(
            "INSERT INTO memory(created_at, summary, tags) VALUES(?,?,?)",
            (ts, summary, json.dumps(tags))
        )
        self._conn().execute("""
            DELETE FROM memory WHERE id NOT IN (
                SELECT id FROM memory ORDER BY created_at DESC LIMIT 20
            )
        """)
        self._conn().commit()

    def load_memory_entries(self, limit: int = 20) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id, created_at, summary, tags FROM memory ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"])
            result.append(d)
        return result

    def delete_all_memory(self):
        self._conn().execute("DELETE FROM memory")
        self._conn().commit()

    def prune_memory_by_age(self, older_than_ts: float, keep_min: int = 5) -> int:
        protected_ids = [
            r[0] for r in self._conn().execute(
                "SELECT id FROM memory ORDER BY created_at DESC LIMIT ?", (keep_min,)
            ).fetchall()
        ]
        if protected_ids:
            placeholders = ",".join("?" * len(protected_ids))
            cur = self._conn().execute(
                f"DELETE FROM memory WHERE created_at < ? AND id NOT IN ({placeholders})",
                (older_than_ts, *protected_ids),
            )
        else:
            cur = self._conn().execute("DELETE FROM memory WHERE created_at < ?", (older_than_ts,))
        deleted = cur.rowcount
        self._conn().commit()
        return deleted

    def init_projects_table(self):
        self._conn().executescript("""
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
        """)
        self._conn().commit()

    def save_project(self, pid: str, name: str, instructions: str, color: str, created_at: str, updated_at: str):
        self._conn().execute("""
            INSERT INTO projects(id, name, instructions, color, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, instructions=excluded.instructions,
                color=excluded.color, updated_at=excluded.updated_at
        """, (pid, name, instructions, color, created_at, updated_at))
        self._conn().commit()

    def load_projects(self) -> list[dict]:
        rows = self._conn().execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_project(self, pid: str):
        self._conn().execute("DELETE FROM projects WHERE id=?", (pid,))
        self._conn().commit()

    def assign_chat_to_project(self, project_id: str, chat_id: str):
        self._conn().execute("INSERT OR IGNORE INTO project_chats(project_id, chat_id) VALUES(?,?)", (project_id, chat_id))
        self._conn().commit()

    def get_project_chats(self, project_id: str) -> list[str]:
        rows = self._conn().execute("SELECT chat_id FROM project_chats WHERE project_id=?", (project_id,)).fetchall()
        return [r["chat_id"] for r in rows]

    def save_pref(self, key: str, value: str):
        self._conn().execute(
            "INSERT INTO user_prefs(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        self._conn().commit()

    def load_pref(self, key: str, default: str = "") -> str:
        row = self._conn().execute("SELECT value FROM user_prefs WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def log_usage(
        self,
        provider: str,
        model: str,
        in_tokens: int,
        out_tokens: int,
        task_type: str = "chat",
        username: str = "",
        cost_usd: float = 0.0,
    ):
        self._conn().execute(
            "INSERT INTO usage_log(ts,provider,model,in_tokens,out_tokens,task_type,username,cost_usd) VALUES(?,?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).timestamp(),
                provider,
                model,
                in_tokens,
                out_tokens,
                task_type,
                (username or "")[:120],
                float(cost_usd or 0.0),
            )
        )
        self._conn().commit()

    def get_usage_stats(self, days: int = 7) -> dict:
        since = datetime.now(timezone.utc).timestamp() - days * 86400
        rows = self._conn().execute(
            "SELECT provider, model, COUNT(*) as calls, SUM(in_tokens) as in_tok, SUM(out_tokens) as out_tok "
            "FROM usage_log WHERE ts >= ? GROUP BY provider, model ORDER BY calls DESC",
            (since,)
        ).fetchall()
        return {"by_provider": [dict(r) for r in rows]}

    def create_user(self, username: str, password_hash: str, display_name: str = "", role: str = "user") -> bool:
        try:
            self._conn().execute(
                "INSERT INTO users(username, password, created_at, display_name, role) VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, datetime.now(timezone.utc).isoformat(), display_name, role)
            )
            self._conn().commit()
            return True
        except sqlite3.IntegrityError: return False

    def get_user(self, username: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

    def user_exists(self, username: str) -> bool:
        return self._conn().execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is not None

    def save_feedback(self, chat_id: str, message_idx: int, reaction: str, provider: str = "", model: str = ""):
        self._conn().execute(
            """INSERT INTO message_feedback(chat_id, message_idx, reaction, provider, model, ts)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(chat_id, message_idx) DO UPDATE SET reaction=excluded.reaction, ts=excluded.ts""",
            (chat_id, message_idx, reaction, provider, model, datetime.now(timezone.utc).timestamp())
        )
        self._conn().commit()

    def list_users(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT username, display_name, created_at, role FROM users ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_user_role(self, username: str, role: str) -> bool:
        cur = self._conn().execute(
            "UPDATE users SET role=? WHERE username=?", (role, username)
        )
        self._conn().commit()
        return cur.rowcount > 0

    def count_users(self) -> int:
        row = self._conn().execute("SELECT COUNT(*) as n FROM users").fetchone()
        return int(row["n"]) if row else 0

    def update_user_email(self, username: str, email: str, verified: bool = False) -> bool:
        cur = self._conn().execute(
            "UPDATE users SET email=?, email_verified=? WHERE username=?",
            (email, 1 if verified else 0, username)
        )
        self._conn().commit()
        return cur.rowcount > 0

    def get_user_by_email(self, email: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None

    def create_api_key(self, key_id: str, username: str, key_hash: str, key_prefix: str,
                       name: str, scopes: list[str], created_at: float) -> bool:
        try:
            self._conn().execute(
                "INSERT INTO auth_api_keys(id,username,key_hash,key_prefix,name,scopes,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (key_id, username, key_hash, key_prefix, name, json.dumps(scopes), created_at)
            )
            self._conn().commit()
            return True
        except Exception:
            return False

    def list_api_keys(self, username: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT id,username,key_prefix,name,scopes,created_at,last_used_at,revoked_at "
            "FROM auth_api_keys WHERE username=? ORDER BY created_at DESC",
            (username,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["scopes"] = json.loads(d["scopes"])
            result.append(d)
        return result

    def get_api_key_by_hash(self, key_hash: str) -> dict | None:
        row = self._conn().execute(
            "SELECT * FROM auth_api_keys WHERE key_hash=? AND revoked_at IS NULL", (key_hash,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["scopes"] = json.loads(d["scopes"])
        return d

    def revoke_api_key(self, key_id: str, username: str) -> bool:
        cur = self._conn().execute(
            "UPDATE auth_api_keys SET revoked_at=? WHERE id=? AND username=?",
            (datetime.now(timezone.utc).timestamp(), key_id, username)
        )
        self._conn().commit()
        return cur.rowcount > 0

    def touch_api_key(self, key_id: str, ts: float) -> None:
        self._conn().execute(
            "UPDATE auth_api_keys SET last_used_at=? WHERE id=?", (ts, key_id)
        )
        self._conn().commit()

    def get_or_create_oauth_user(self, provider: str, provider_id: str,
                                  email: str, display_name: str) -> dict:
        row = self._conn().execute(
            "SELECT username FROM oauth_accounts WHERE provider=? AND provider_id=?",
            (provider, provider_id)
        ).fetchone()
        if row:
            user = self.get_user(row["username"])
            return user if user else {}
        import uuid as _uuid
        username = f"{provider}_{provider_id[:16]}_{_uuid.uuid4().hex[:6]}"
        role = "admin" if self.count_users() == 0 else "user"
        self.create_user(username, "", display_name, role)
        self.update_user_email(username, email, verified=True)
        oid = _uuid.uuid4().hex
        self._conn().execute(
            "INSERT OR IGNORE INTO oauth_accounts(id,username,provider,provider_id) VALUES(?,?,?,?)",
            (oid, username, provider, provider_id)
        )
        self._conn().commit()
        return self.get_user(username) or {}

# ── POSTGRES BACKEND ──────────────────────────────────────────────────────────

class PostgresBackend(DatabaseBackend):
    def __init__(self, url: str):
        # Support PgBouncer DSN override: PGBOUNCER_DSN takes priority over DATABASE_URL.
        # When PGBOUNCER_DSN is set, prepared statements are disabled if
        # DB_POOL_MODE=statement (statement-level PgBouncer doesn't support them).
        pgbouncer_dsn = os.getenv("PGBOUNCER_DSN", "").strip()
        self.url = pgbouncer_dsn if pgbouncer_dsn else url
        self._pool_mode = os.getenv("DB_POOL_MODE", "session").lower()  # session|transaction|statement
        self._pool = None
        self._pool_lock = threading.Lock()

    def _get_pool(self):
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    import psycopg2.pool
                    min_conn = int(os.getenv("PG_POOL_MIN", "2"))
                    max_conn = int(os.getenv("PG_POOL_SIZE", "10"))
                    self._pool = psycopg2.pool.ThreadedConnectionPool(
                        minconn=min_conn, maxconn=max_conn,
                        dsn=self.url
                    )
        return self._pool

    def _get_conn(self):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        try:
            pool = self._get_pool()
            conn = pool.getconn()
            conn.cursor_factory = RealDictCursor
            # For statement-level PgBouncer: disable autocommit prepared statements
            if self._pool_mode == "statement":
                conn.autocommit = False
            return conn
        except Exception:
            return psycopg2.connect(self.url, cursor_factory=RealDictCursor)

    def _put_conn(self, conn):
        try:
            pool = self._get_pool()
            pool.putconn(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    @contextlib.contextmanager
    def _db(self):
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def init_db(self):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    messages    JSONB NOT NULL,
                    pinned      INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS shares (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    messages    JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory (
                    id          SERIAL PRIMARY KEY,
                    created_at  DOUBLE PRECISION NOT NULL,
                    summary     TEXT NOT NULL,
                    tags        JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_prefs (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_log (
                    id          SERIAL PRIMARY KEY,
                    ts          DOUBLE PRECISION NOT NULL,
                    provider    TEXT NOT NULL,
                    model       TEXT NOT NULL,
                    in_tokens   INTEGER NOT NULL DEFAULT 0,
                    out_tokens  INTEGER NOT NULL DEFAULT 0,
                    task_type   TEXT NOT NULL DEFAULT 'chat',
                    username    TEXT NOT NULL DEFAULT '',
                    cost_usd    DOUBLE PRECISION NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS users (
                    username    TEXT PRIMARY KEY,
                    password    TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    display_name TEXT,
                    role        TEXT NOT NULL DEFAULT 'user',
                    email       TEXT,
                    email_verified INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS message_feedback (
                    id          SERIAL PRIMARY KEY,
                    chat_id     TEXT NOT NULL,
                    message_idx INTEGER NOT NULL,
                    reaction    TEXT NOT NULL,
                    provider    TEXT NOT NULL DEFAULT '',
                    model       TEXT NOT NULL DEFAULT '',
                    ts          DOUBLE PRECISION NOT NULL,
                    UNIQUE (chat_id, message_idx)
                );
                CREATE TABLE IF NOT EXISTS auth_api_keys (
                    id           TEXT PRIMARY KEY,
                    username     TEXT NOT NULL,
                    key_hash     TEXT NOT NULL UNIQUE,
                    key_prefix   TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    scopes       TEXT NOT NULL,
                    created_at   DOUBLE PRECISION NOT NULL,
                    last_used_at DOUBLE PRECISION,
                    revoked_at   DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS oauth_accounts (
                    id          TEXT PRIMARY KEY,
                    username    TEXT NOT NULL,
                    provider    TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    UNIQUE(provider, provider_id)
                );
                CREATE TABLE IF NOT EXISTS fine_tuning_jobs (
                    id               TEXT PRIMARY KEY,
                    created_at       INTEGER NOT NULL,
                    finished_at      INTEGER,
                    model            TEXT NOT NULL,
                    fine_tuned_model TEXT,
                    organization_id  TEXT NOT NULL,
                    status           TEXT NOT NULL,
                    training_file    TEXT NOT NULL,
                    validation_file  TEXT,
                    hyperparameters  TEXT NOT NULL,
                    trained_tokens   INTEGER,
                    error            TEXT,
                    result_files     TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fine_tuning_job_events (
                    id               TEXT PRIMARY KEY,
                    job_id           TEXT NOT NULL,
                    created_at       INTEGER NOT NULL,
                    level            TEXT NOT NULL DEFAULT 'info',
                    message          TEXT NOT NULL,
                    data             TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS execution_traces (
                    trace_id    TEXT PRIMARY KEY,
                    events      TEXT NOT NULL DEFAULT '[]',
                    created_at  DOUBLE PRECISION NOT NULL,
                    updated_at  DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS autonomy_traces (
                    trace_id    TEXT PRIMARY KEY,
                    data        TEXT NOT NULL DEFAULT '{}',
                    created_at  DOUBLE PRECISION NOT NULL,
                    updated_at  DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_shared_memory (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL DEFAULT 'null',
                    updated_at  DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_queue_jobs (
                    task_id       TEXT PRIMARY KEY,
                    description   TEXT NOT NULL,
                    priority      INTEGER NOT NULL DEFAULT 5,
                    dependencies  TEXT NOT NULL DEFAULT '[]',
                    metadata      TEXT NOT NULL DEFAULT '{}',
                    schedule_cron TEXT NOT NULL DEFAULT '',
                    status        TEXT NOT NULL DEFAULT 'pending',
                    result        TEXT NOT NULL DEFAULT '',
                    error         TEXT NOT NULL DEFAULT '',
                    created_at    DOUBLE PRECISION NOT NULL,
                    started_at    DOUBLE PRECISION,
                    finished_at   DOUBLE PRECISION
                );
                CREATE TABLE IF NOT EXISTS ft_training_samples (
                    id          TEXT PRIMARY KEY,
                    created_at  DOUBLE PRECISION NOT NULL,
                    task        TEXT NOT NULL,
                    result      TEXT NOT NULL,
                    quality     DOUBLE PRECISION NOT NULL DEFAULT 0.7,
                    lessons     TEXT NOT NULL DEFAULT '[]',
                    source      TEXT NOT NULL DEFAULT 'reflection'
                );
            """)
            for col_sql in [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS username TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0",
            ]:
                try:
                    cur.execute(col_sql)
                except Exception:
                    pass
        conn.commit()
        # New tables: orgs, feature_flags, audit_log, MFA, login_attempts
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orgs (
                    id             TEXT PRIMARY KEY,
                    name           TEXT NOT NULL,
                    owner          TEXT NOT NULL,
                    plan           TEXT NOT NULL DEFAULT 'free',
                    metadata       TEXT NOT NULL DEFAULT '{}',
                    tokens_per_day INTEGER NOT NULL DEFAULT 0,
                    spend_cap_usd  DOUBLE PRECISION NOT NULL DEFAULT 0,
                    created_at     DOUBLE PRECISION NOT NULL,
                    updated_at     DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS org_members (
                    id         SERIAL PRIMARY KEY,
                    org_id     TEXT NOT NULL,
                    username   TEXT NOT NULL,
                    role       TEXT NOT NULL DEFAULT 'member',
                    joined_at  DOUBLE PRECISION NOT NULL,
                    UNIQUE(org_id, username)
                );
                CREATE TABLE IF NOT EXISTS org_invites (
                    id          SERIAL PRIMARY KEY,
                    org_id      TEXT NOT NULL,
                    token       TEXT NOT NULL UNIQUE,
                    invited_by  TEXT NOT NULL,
                    email       TEXT NOT NULL DEFAULT '',
                    role        TEXT NOT NULL DEFAULT 'member',
                    expires_at  DOUBLE PRECISION NOT NULL,
                    used        INTEGER NOT NULL DEFAULT 0,
                    used_by     TEXT NOT NULL DEFAULT '',
                    created_at  DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mfa_secrets (
                    username    TEXT PRIMARY KEY,
                    secret      TEXT NOT NULL,
                    enabled     INTEGER NOT NULL DEFAULT 0,
                    created_at  DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
                    id          SERIAL PRIMARY KEY,
                    username    TEXT NOT NULL,
                    code_hash   TEXT NOT NULL,
                    used        INTEGER NOT NULL DEFAULT 0,
                    created_at  DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id          SERIAL PRIMARY KEY,
                    username    TEXT NOT NULL,
                    ip_address  TEXT NOT NULL DEFAULT '',
                    success     INTEGER NOT NULL DEFAULT 0,
                    ts          DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trusted_devices (
                    id          SERIAL PRIMARY KEY,
                    username    TEXT NOT NULL,
                    device_hash TEXT NOT NULL,
                    label       TEXT NOT NULL DEFAULT '',
                    created_at  DOUBLE PRECISION NOT NULL,
                    last_seen   DOUBLE PRECISION NOT NULL,
                    UNIQUE(username, device_hash)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          SERIAL PRIMARY KEY,
                    ts          DOUBLE PRECISION NOT NULL,
                    actor       TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    resource    TEXT NOT NULL DEFAULT '',
                    result      TEXT NOT NULL DEFAULT 'ok',
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    request_id  TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS feature_flags (
                    name                TEXT PRIMARY KEY,
                    enabled             INTEGER NOT NULL DEFAULT 0,
                    description         TEXT NOT NULL DEFAULT '',
                    rollout_percentage  INTEGER NOT NULL DEFAULT 0,
                    user_overrides      TEXT NOT NULL DEFAULT '{}',
                    org_overrides       TEXT NOT NULL DEFAULT '{}',
                    value               TEXT NOT NULL DEFAULT '',
                    updated_at          DOUBLE PRECISION NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backup_log (
                    id         SERIAL PRIMARY KEY,
                    ts         DOUBLE PRECISION NOT NULL,
                    type       TEXT NOT NULL DEFAULT 'local',
                    status     TEXT NOT NULL DEFAULT 'ok',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    location   TEXT NOT NULL DEFAULT '',
                    checksum   TEXT NOT NULL DEFAULT '',
                    error      TEXT NOT NULL DEFAULT ''
                );
            """)
        conn.commit()
        self._put_conn(conn)

    def save_chat(self, cid: str, title: str, created_at: str, updated_at: str, messages: list):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO chats(id, title, created_at, updated_at, messages)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    title=EXCLUDED.title, updated_at=EXCLUDED.updated_at, messages=EXCLUDED.messages
            """, (cid, title[:80], created_at, updated_at, json.dumps(messages)))
        conn.commit()
        conn.close()

    def load_chats(self) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, created_at, updated_at, messages FROM chats ORDER BY updated_at DESC")
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def load_chat(self, cid: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, created_at, updated_at, messages FROM chats WHERE id=%s", (cid,))
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_chat(self, cid: str):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chats WHERE id=%s", (cid,))
        conn.commit()
        conn.close()

    def save_share(self, sid: str, title: str, created_at: str, messages: list):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO shares(id, title, created_at, messages) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                       (sid, title, created_at, json.dumps(messages)))
        conn.commit()
        conn.close()

    def load_share(self, sid: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, created_at, messages FROM shares WHERE id=%s", (sid,))
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def add_memory_entry(self, summary: str, tags: list, ts: float):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO memory(created_at, summary, tags) VALUES(%s,%s,%s)", (ts, summary, json.dumps(tags)))
            cur.execute("DELETE FROM memory WHERE id NOT IN (SELECT id FROM memory ORDER BY created_at DESC LIMIT 20)")
        conn.commit()
        conn.close()

    def load_memory_entries(self, limit: int = 20) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, created_at, summary, tags FROM memory ORDER BY created_at DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_all_memory(self):
        conn = self._get_conn()
        with conn.cursor() as cur: cur.execute("DELETE FROM memory")
        conn.commit()
        conn.close()

    def prune_memory_by_age(self, older_than_ts: float, keep_min: int = 5) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM memory ORDER BY created_at DESC LIMIT %s", (keep_min,))
            protected_ids = [r["id"] for r in cur.fetchall()]
            if protected_ids:
                cur.execute("DELETE FROM memory WHERE created_at < %s AND id != ALL(%s)", (older_than_ts, protected_ids))
            else:
                cur.execute("DELETE FROM memory WHERE created_at < %s", (older_than_ts,))
            deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted

    def init_projects_table(self):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    color        TEXT NOT NULL DEFAULT '#7c6af7'
                );
                CREATE TABLE IF NOT EXISTS project_chats (
                    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    chat_id     TEXT NOT NULL REFERENCES chats(id)    ON DELETE CASCADE,
                    PRIMARY KEY (project_id, chat_id)
                );
            """)
        conn.commit()
        conn.close()

    def save_project(self, pid: str, name: str, instructions: str, color: str, created_at: str, updated_at: str):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO projects(id, name, instructions, color, created_at, updated_at)
                VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET
                    name=EXCLUDED.name, instructions=EXCLUDED.instructions,
                    color=EXCLUDED.color, updated_at=EXCLUDED.updated_at
            """, (pid, name, instructions, color, created_at, updated_at))
        conn.commit()
        conn.close()

    def load_projects(self) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM projects ORDER BY updated_at DESC")
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_project(self, pid: str):
        conn = self._get_conn()
        with conn.cursor() as cur: cur.execute("DELETE FROM projects WHERE id=%s", (pid,))
        conn.commit()
        conn.close()

    def assign_chat_to_project(self, project_id: str, chat_id: str):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO project_chats(project_id, chat_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (project_id, chat_id))
        conn.commit()
        conn.close()

    def get_project_chats(self, project_id: str) -> list[str]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM project_chats WHERE project_id=%s", (project_id,))
            rows = cur.fetchall()
        conn.close()
        return [r["chat_id"] for r in rows]

    def save_pref(self, key: str, value: str):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO user_prefs(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (key, value))
        conn.commit()
        conn.close()

    def load_pref(self, key: str, default: str = "") -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM user_prefs WHERE key=%s", (key,))
            row = cur.fetchone()
        conn.close()
        return row["value"] if row else default

    def log_usage(
        self,
        provider: str,
        model: str,
        in_tokens: int,
        out_tokens: int,
        task_type: str = "chat",
        username: str = "",
        cost_usd: float = 0.0,
    ):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO usage_log(ts,provider,model,in_tokens,out_tokens,task_type,username,cost_usd) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    datetime.now(timezone.utc).timestamp(),
                    provider,
                    model,
                    in_tokens,
                    out_tokens,
                    task_type,
                    (username or "")[:120],
                    float(cost_usd or 0.0),
                ),
            )
        conn.commit()
        conn.close()

    def get_usage_stats(self, days: int = 7) -> dict:
        since = datetime.now(timezone.utc).timestamp() - days * 86400
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT provider, model, COUNT(*) as calls, SUM(in_tokens) as in_tok, SUM(out_tokens) as out_tok "
                        "FROM usage_log WHERE ts >= %s GROUP BY provider, model ORDER BY calls DESC", (since,))
            rows = cur.fetchall()
        conn.close()
        return {"by_provider": [dict(r) for r in rows]}

    def create_user(self, username: str, password_hash: str, display_name: str = "", role: str = "user") -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users(username, password, created_at, display_name, role) VALUES (%s, %s, %s, %s, %s)",
                    (username, password_hash, datetime.now(timezone.utc).isoformat(), display_name, role)
                )
            conn.commit()
            return True
        except Exception: return False
        finally: self._put_conn(conn)

    def get_user(self, username: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username=%s", (username,))
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def user_exists(self, username: str) -> bool:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE username=%s", (username,))
            row = cur.fetchone()
        conn.close()
        return row is not None

    def save_feedback(self, chat_id: str, message_idx: int, reaction: str, provider: str = "", model: str = ""):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO message_feedback(chat_id, message_idx, reaction, provider, model, ts)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT(chat_id, message_idx) DO UPDATE SET reaction=EXCLUDED.reaction, ts=EXCLUDED.ts""",
                        (chat_id, message_idx, reaction, provider, model, datetime.now(timezone.utc).timestamp()))
        conn.commit()
        self._put_conn(conn)

    def list_users(self) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT username, display_name, created_at, role FROM users ORDER BY created_at ASC")
            rows = cur.fetchall()
        self._put_conn(conn)
        return [dict(r) for r in rows]

    def update_user_role(self, username: str, role: str) -> bool:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role=%s WHERE username=%s", (role, username))
            changed = cur.rowcount > 0
        conn.commit()
        self._put_conn(conn)
        return changed

    def count_users(self) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as n FROM users")
            row = cur.fetchone()
        self._put_conn(conn)
        return int(row["n"]) if row else 0

    def update_user_email(self, username: str, email: str, verified: bool = False) -> bool:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET email=%s, email_verified=%s WHERE username=%s",
                        (email, 1 if verified else 0, username))
            changed = cur.rowcount > 0
        conn.commit()
        self._put_conn(conn)
        return changed

    def get_user_by_email(self, email: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email=%s", (email,))
            row = cur.fetchone()
        self._put_conn(conn)
        return dict(row) if row else None

    def create_api_key(self, key_id: str, username: str, key_hash: str, key_prefix: str,
                       name: str, scopes: list[str], created_at: float) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO auth_api_keys(id,username,key_hash,key_prefix,name,scopes,created_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (key_id, username, key_hash, key_prefix, name, json.dumps(scopes), created_at)
                )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            self._put_conn(conn)

    def list_api_keys(self, username: str) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id,username,key_prefix,name,scopes,created_at,last_used_at,revoked_at "
                "FROM auth_api_keys WHERE username=%s ORDER BY created_at DESC",
                (username,)
            )
            rows = cur.fetchall()
        self._put_conn(conn)
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("scopes"), str):
                d["scopes"] = json.loads(d["scopes"])
            result.append(d)
        return result

    def get_api_key_by_hash(self, key_hash: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM auth_api_keys WHERE key_hash=%s AND revoked_at IS NULL", (key_hash,))
            row = cur.fetchone()
        self._put_conn(conn)
        if not row:
            return None
        d = dict(row)
        if isinstance(d.get("scopes"), str):
            d["scopes"] = json.loads(d["scopes"])
        return d

    def revoke_api_key(self, key_id: str, username: str) -> bool:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("UPDATE auth_api_keys SET revoked_at=%s WHERE id=%s AND username=%s",
                        (datetime.now(timezone.utc).timestamp(), key_id, username))
            changed = cur.rowcount > 0
        conn.commit()
        self._put_conn(conn)
        return changed

    def touch_api_key(self, key_id: str, ts: float) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("UPDATE auth_api_keys SET last_used_at=%s WHERE id=%s", (ts, key_id))
        conn.commit()
        self._put_conn(conn)

    def get_or_create_oauth_user(self, provider: str, provider_id: str,
                                  email: str, display_name: str) -> dict:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM oauth_accounts WHERE provider=%s AND provider_id=%s",
                        (provider, provider_id))
            row = cur.fetchone()
        self._put_conn(conn)
        if row:
            return self.get_user(row["username"]) or {}
        import uuid as _uuid
        username = f"{provider}_{provider_id[:16]}_{_uuid.uuid4().hex[:6]}"
        role = "admin" if self.count_users() == 0 else "user"
        self.create_user(username, "", display_name, role)
        self.update_user_email(username, email, verified=True)
        oid = _uuid.uuid4().hex
        conn2 = self._get_conn()
        with conn2.cursor() as cur:
            cur.execute("INSERT INTO oauth_accounts(id,username,provider,provider_id) VALUES(%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING", (oid, username, provider, provider_id))
        conn2.commit()
        self._put_conn(conn2)
        return self.get_user(username) or {}

# ── FACTORY ──────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_backend() -> DatabaseBackend:
    if DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://"):
        return PostgresBackend(DATABASE_URL)
    return SQLiteBackend(os.getenv("DB_PATH", "/tmp/nexus_ai.db"))

_backend = get_backend()

# ── EXPORTED WRAPPERS (for backward compatibility) ──────────────────────────

def init_db(): _backend.init_db()
def save_chat(cid, title, created_at, updated_at, messages): _backend.save_chat(cid, title, created_at, updated_at, messages)
def load_chats(): return _backend.load_chats()
def load_chat(cid): return _backend.load_chat(cid)
def delete_chat(cid): _backend.delete_chat(cid)
def save_share(sid, title, created_at, messages): _backend.save_share(sid, title, created_at, messages)
def load_share(sid): return _backend.load_share(sid)
def add_memory_entry(summary, tags, ts): _backend.add_memory_entry(summary, tags, ts)
def load_memory_entries(limit=20): return _backend.load_memory_entries(limit)
def delete_all_memory(): _backend.delete_all_memory()
def prune_memory_by_age(older_than_ts, keep_min=5): return _backend.prune_memory_by_age(older_than_ts, keep_min)
def init_projects_table(): _backend.init_projects_table()
def save_project(pid, name, instructions, color, created_at, updated_at): _backend.save_project(pid, name, instructions, color, created_at, updated_at)
def load_projects(): return _backend.load_projects()
def delete_project(pid): _backend.delete_project(pid)
def assign_chat_to_project(project_id, chat_id): _backend.assign_chat_to_project(project_id, chat_id)
def get_project_chats(project_id): return _backend.get_project_chats(project_id)
def save_pref(key, value): _backend.save_pref(key, value)
def load_pref(key, default=""): return _backend.load_pref(key, default)
def log_usage(p, m, it, ot, tt="chat", username="", cost_usd=0.0):
    _backend.log_usage(p, m, it, ot, tt, username=username, cost_usd=cost_usd)
def get_usage_stats(days=7): return _backend.get_usage_stats(days)
def create_user(u, p, d="", role="user"): return _backend.create_user(u, p, d, role)
def get_user(u): return _backend.get_user(u)
def user_exists(u): return _backend.user_exists(u)
def save_feedback(chat_id, message_idx, reaction, provider="", model=""):
    _backend.save_feedback(chat_id, message_idx, reaction, provider, model)
def list_users(): return _backend.list_users()
def update_user_role(username, role): return _backend.update_user_role(username, role)
def count_users(): return _backend.count_users()
def update_user_email(username, email, verified=False): return _backend.update_user_email(username, email, verified)
def get_user_by_email(email): return _backend.get_user_by_email(email)
def create_api_key(key_id, username, key_hash, key_prefix, name, scopes, created_at): return _backend.create_api_key(key_id, username, key_hash, key_prefix, name, scopes, created_at)
def list_api_keys(username): return _backend.list_api_keys(username)
def get_api_key_by_hash(key_hash): return _backend.get_api_key_by_hash(key_hash)
def revoke_api_key(key_id, username): return _backend.revoke_api_key(key_id, username)
def touch_api_key(key_id, ts): return _backend.touch_api_key(key_id, ts)
def get_or_create_oauth_user(provider, provider_id, email, display_name): return _backend.get_or_create_oauth_user(provider, provider_id, email, display_name)

# Special cases (mapped to pref table)
def save_custom_instructions(i): save_pref("custom_instructions", i)
def load_custom_instructions(): return load_pref("custom_instructions", "")


def _sql_fetchall(sql: str, params: tuple = ()) -> list[dict]:
    if isinstance(_backend, SQLiteBackend):
        rows = _backend._conn().execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    if isinstance(_backend, PostgresBackend):
        conn = _backend._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    return []


def _sql_execute(sql: str, params: tuple = ()) -> int:
    if isinstance(_backend, SQLiteBackend):
        cur = _backend._conn().execute(sql, params)
        _backend._conn().commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)
    if isinstance(_backend, PostgresBackend):
        conn = _backend._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                changed = int(cur.rowcount if cur.rowcount is not None else 0)
            conn.commit()
            return changed
        finally:
            conn.close()
    return 0


def init_usage_table():
    init_db()


def init_users_table():
    init_db()


def update_memory_entry(entry_id: int, summary: str):
    if isinstance(_backend, SQLiteBackend):
        _sql_execute("UPDATE memory SET summary=? WHERE id=?", (summary, int(entry_id)))
    else:
        _sql_execute("UPDATE memory SET summary=%s WHERE id=%s", (summary, int(entry_id)))


def delete_memory_entry(entry_id: int):
    if isinstance(_backend, SQLiteBackend):
        _sql_execute("DELETE FROM memory WHERE id=?", (int(entry_id),))
    else:
        _sql_execute("DELETE FROM memory WHERE id=%s", (int(entry_id),))


def pin_chat(cid: str, pinned: bool = True):
    flag = 1 if pinned else 0
    try:
        if isinstance(_backend, SQLiteBackend):
            _sql_execute("UPDATE chats SET pinned=? WHERE id=?", (flag, cid))
        else:
            _sql_execute("UPDATE chats SET pinned=%s WHERE id=%s", (flag, cid))
    except Exception:
        # Backward compatibility with older schemas that do not have pinned column.
        pass


def get_pinned_chats() -> list[str]:
    try:
        rows = _sql_fetchall("SELECT id FROM chats WHERE pinned=1 ORDER BY updated_at DESC")
        return [str(r.get("id")) for r in rows]
    except Exception:
        return []


def search_chats(q: str) -> list[dict]:
    needle = (q or "").strip().lower()
    if not needle:
        return []
    results = []
    for row in load_chats():
        title = str(row.get("title") or "")
        messages = str(row.get("messages") or "")
        haystack = (title + "\n" + messages).lower()
        if needle in haystack:
            results.append(
                {
                    "id": row.get("id"),
                    "title": title,
                    "updated_at": row.get("updated_at"),
                    "snippet": title[:180],
                }
            )
    return results[:100]


def get_usage_daily(days: int = 7) -> list[dict]:
    safe_days = max(1, min(int(days), 365))
    since = datetime.now(timezone.utc).timestamp() - safe_days * 86400
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall(
            "SELECT ts, in_tokens, out_tokens FROM usage_log WHERE ts >= ? ORDER BY ts ASC",
            (since,),
        )
    else:
        rows = _sql_fetchall(
            "SELECT ts, in_tokens, out_tokens FROM usage_log WHERE ts >= %s ORDER BY ts ASC",
            (since,),
        )

    by_day: dict[str, dict] = {}
    for r in rows:
        ts = float(r.get("ts") or 0.0)
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        item = by_day.setdefault(day, {"date": day, "calls": 0, "in_tok": 0, "out_tok": 0})
        item["calls"] += 1
        item["in_tok"] += int(r.get("in_tokens") or 0)
        item["out_tok"] += int(r.get("out_tokens") or 0)
    return list(by_day.values())


def get_usage_records(days: int = 7, username: str = "", limit: int = 5000) -> list[dict]:
    safe_days = max(1, min(int(days), 365))
    safe_limit = max(1, min(int(limit), 50000))
    since = datetime.now(timezone.utc).timestamp() - safe_days * 86400
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"

    clauses = [f"ts >= {ph}"]
    params: list = [since]
    if (username or "").strip():
        clauses.append(f"username = {ph}")
        params.append((username or "").strip())

    where_sql = " AND ".join(clauses)
    query = (
        "SELECT ts, provider, model, in_tokens, out_tokens, task_type, username, cost_usd "
        f"FROM usage_log WHERE {where_sql} ORDER BY ts DESC LIMIT {safe_limit}"
    )

    try:
        rows = _sql_fetchall(query, tuple(params))
    except Exception:
        # Backward compatibility for old DBs without username/cost_usd.
        fallback_query = (
            "SELECT ts, provider, model, in_tokens, out_tokens, task_type "
            f"FROM usage_log WHERE ts >= {ph} ORDER BY ts DESC LIMIT {safe_limit}"
        )
        rows = _sql_fetchall(fallback_query, (since,))

    normalized: list[dict] = []
    for row in rows:
        item = dict(row)
        item.setdefault("username", "")
        item.setdefault("cost_usd", 0.0)
        normalized.append(item)
    return normalized


def get_usage_by_user(days: int = 7, limit: int = 200) -> list[dict]:
    rows = get_usage_records(days=days, username="", limit=50000)
    buckets: dict[str, dict] = {}
    for row in rows:
        user_key = str(row.get("username") or "anonymous").strip() or "anonymous"
        item = buckets.setdefault(
            user_key,
            {
                "username": user_key,
                "calls": 0,
                "in_tok": 0,
                "out_tok": 0,
                "cost_usd": 0.0,
            },
        )
        item["calls"] += 1
        item["in_tok"] += int(row.get("in_tokens") or 0)
        item["out_tok"] += int(row.get("out_tokens") or 0)
        item["cost_usd"] = round(float(item["cost_usd"]) + float(row.get("cost_usd") or 0.0), 6)

    result = sorted(buckets.values(), key=lambda v: (v["calls"], v["out_tok"]), reverse=True)
    return result[: max(1, min(int(limit), 1000))]


def _load_json_pref(key: str, default):
    raw = load_pref(key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _save_json_pref(key: str, value):
    save_pref(key, json.dumps(value, separators=(",", ":")))


def save_custom_persona(pid: str, name: str, icon: str, description: str, prompt_prefix: str,
                        color: str, temperature: float, tier: str):
    personas = _load_json_pref("custom_personas", [])
    record = {
        "id": pid,
        "name": name,
        "icon": icon,
        "description": description,
        "prompt_prefix": prompt_prefix,
        "color": color,
        "temperature": float(temperature),
        "tier": tier,
    }
    personas = [p for p in personas if p.get("id") != pid]
    personas.append(record)
    _save_json_pref("custom_personas", personas)


def load_custom_personas() -> list[dict]:
    data = _load_json_pref("custom_personas", [])
    return data if isinstance(data, list) else []


def delete_custom_persona(pid: str):
    personas = [p for p in load_custom_personas() if p.get("id") != pid]
    _save_json_pref("custom_personas", personas)


def save_self_review(review_id: str, traces_analyzed: int, insights: list, suggestions: list, provider: str):
    reviews = _load_json_pref("self_reviews", [])
    reviews.append(
        {
            "review_id": review_id,
            "traces_analyzed": int(traces_analyzed),
            "insights": list(insights or []),
            "suggestions": list(suggestions or []),
            "provider": provider,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_json_pref("self_reviews", reviews[-200:])


def list_self_reviews(limit: int = 10) -> list[dict]:
    reviews = _load_json_pref("self_reviews", [])
    if not isinstance(reviews, list):
        return []
    return list(reversed(reviews))[: max(1, min(int(limit), 200))]


def _canonicalize_safety_audit_entry(entry: dict) -> str:
    payload = {
        k: v for k, v in dict(entry or {}).items()
        if k not in {"entry_hash", "previous_hash", "integrity_ok"}
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_safety_audit_hash(entry: dict, previous_hash: str = "") -> str:
    material = f"{previous_hash}|{_canonicalize_safety_audit_entry(entry)}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def load_safety_audit_entries(limit: int = 100, session_id: str = "", event_type: str = "") -> list[dict]:
    events = _load_json_pref("safety_audit_log", [])
    if not isinstance(events, list):
        return []
    filtered = []
    for ev in events:
        if session_id and str(ev.get("session_id") or ev.get("session") or "") != session_id:
            continue
        if event_type and str(ev.get("event_type") or ev.get("type") or "") != event_type:
            continue
        filtered.append(ev)
    return list(reversed(filtered))[: max(1, min(int(limit), 5000))]


def verify_safety_audit_entries(limit: int = 5000) -> dict:
    events = _load_json_pref("safety_audit_log", [])
    if not isinstance(events, list):
        events = []
    relevant = events[-max(1, min(int(limit), 5000)):]
    previous_hash = ""
    broken_at = None
    for idx, event in enumerate(relevant, start=1):
        expected = _compute_safety_audit_hash(event, previous_hash=previous_hash)
        actual = str(event.get("entry_hash") or "")
        if actual != expected:
            broken_at = idx
            break
        previous_hash = actual
    return {
        "ok": broken_at is None,
        "checked": len(relevant),
        "broken_at": broken_at,
        "head_hash": previous_hash or None,
    }


def add_safety_audit_entry(entry: dict):
    events = _load_json_pref("safety_audit_log", [])
    if not isinstance(events, list):
        events = []
    payload = dict(entry or {})
    payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    payload.pop("integrity_ok", None)
    previous_hash = str(events[-1].get("entry_hash") or "") if events else ""
    payload["previous_hash"] = previous_hash or None
    payload["entry_hash"] = _compute_safety_audit_hash(payload, previous_hash=previous_hash)
    events.append(payload)
    _save_json_pref("safety_audit_log", events[-5000:])


def clear_safety_audit_entries():
    _save_json_pref("safety_audit_log", [])


def save_benchmark_result(
    provider: str,
    probe_name: str,
    latency_ms: float,
    response_len: int,
    model: str = "",
    task_type: str = "",
):
    rows = _load_json_pref("benchmark_results", [])
    resolved_task_type = str(task_type or probe_name or "chat").strip().lower()
    rows.append(
        {
            "provider": provider,
            "model": str(model or "").strip(),
            "probe": probe_name,
            "task_type": resolved_task_type,
            "latency_ms": float(latency_ms),
            "response_len": int(response_len),
            "ts": datetime.now(timezone.utc).timestamp(),
        }
    )
    _save_json_pref("benchmark_results", rows[-2000:])


def load_benchmark_results(limit: int = 200) -> list[dict]:
    rows = _load_json_pref("benchmark_results", [])
    if not isinstance(rows, list):
        return []
    return list(reversed(rows))[: max(1, min(int(limit), 5000))]


def load_feedback_export(limit: int = 5000) -> list[dict]:
    safe_limit = max(1, min(int(limit), 50000))
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall(
            "SELECT chat_id, message_idx, reaction, provider, model, ts FROM message_feedback ORDER BY ts DESC LIMIT ?",
            (safe_limit,),
        )
    else:
        rows = _sql_fetchall(
            "SELECT chat_id, message_idx, reaction, provider, model, ts FROM message_feedback ORDER BY ts DESC LIMIT %s",
            (safe_limit,),
        )
    return rows


# ── Durable scheduler persistence helpers ───────────────────────────────────

def _normalize_scheduled_job_row(row: dict) -> dict:
    out = dict(row or {})
    logs = out.get("logs", [])
    if isinstance(logs, str):
        try:
            logs = json.loads(logs)
        except Exception:
            logs = []
    if not isinstance(logs, list):
        logs = []
    out["logs"] = logs
    out["id"] = str(out.get("id") or "").strip()
    return out


def load_scheduled_jobs() -> list[dict]:
    rows = _load_json_pref("scheduled_jobs", [])
    if not isinstance(rows, list):
        return []
    return [_normalize_scheduled_job_row(r) for r in rows if isinstance(r, dict) and str(r.get("id") or "").strip()]


def upsert_scheduled_job(job: dict) -> None:
    item = _normalize_scheduled_job_row(job)
    if not item.get("id"):
        return
    rows = load_scheduled_jobs()
    updated = False
    for idx, row in enumerate(rows):
        if row.get("id") == item["id"]:
            rows[idx] = item
            updated = True
            break
    if not updated:
        rows.append(item)
    _save_json_pref("scheduled_jobs", rows)


def delete_scheduled_job(job_id: str) -> None:
    target = str(job_id or "").strip()
    if not target:
        return
    rows = [r for r in load_scheduled_jobs() if r.get("id") != target]
    _save_json_pref("scheduled_jobs", rows)


def clear_scheduled_jobs() -> None:
    _save_json_pref("scheduled_jobs", [])


def clear_scheduled_job(job_id: str | None = None) -> None:
    if job_id:
        delete_scheduled_job(job_id)
        return
    clear_scheduled_jobs()


# ── Fine-tuning jobs persistence ────────────────────────────────────────────

def _decode_ft_row(row: dict) -> dict:
    out = dict(row)
    for key, default in (("hyperparameters", {}), ("result_files", []), ("error", None)):
        val = out.get(key)
        if isinstance(val, str) and val:
            try:
                out[key] = json.loads(val)
            except Exception:
                out[key] = default
        elif val in (None, ""):
            out[key] = default
    return out


def create_fine_tuning_job(job: dict) -> bool:
    hp = json.dumps(job.get("hyperparameters") or {})
    err = json.dumps(job.get("error")) if job.get("error") is not None else None
    files = json.dumps(job.get("result_files") or [])
    if isinstance(_backend, SQLiteBackend):
        changed = _sql_execute(
            "INSERT INTO fine_tuning_jobs(id, created_at, finished_at, model, fine_tuned_model, organization_id, status, training_file, validation_file, hyperparameters, trained_tokens, error, result_files) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job.get("id"),
                int(job.get("created_at") or 0),
                job.get("finished_at"),
                job.get("model"),
                job.get("fine_tuned_model"),
                job.get("organization_id") or "org-nexus",
                job.get("status") or "queued",
                job.get("training_file"),
                job.get("validation_file"),
                hp,
                job.get("trained_tokens"),
                err,
                files,
            ),
        )
    else:
        changed = _sql_execute(
            "INSERT INTO fine_tuning_jobs(id, created_at, finished_at, model, fine_tuned_model, organization_id, status, training_file, validation_file, hyperparameters, trained_tokens, error, result_files) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                job.get("id"),
                int(job.get("created_at") or 0),
                job.get("finished_at"),
                job.get("model"),
                job.get("fine_tuned_model"),
                job.get("organization_id") or "org-nexus",
                job.get("status") or "queued",
                job.get("training_file"),
                job.get("validation_file"),
                hp,
                job.get("trained_tokens"),
                err,
                files,
            ),
        )
    return changed > 0


def get_fine_tuning_job(job_id: str) -> dict | None:
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall("SELECT * FROM fine_tuning_jobs WHERE id=?", (job_id,))
    else:
        rows = _sql_fetchall("SELECT * FROM fine_tuning_jobs WHERE id=%s", (job_id,))
    if not rows:
        return None
    return _decode_ft_row(rows[0])


def list_fine_tuning_jobs(limit: int = 20, after: str = "") -> list[dict]:
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall("SELECT * FROM fine_tuning_jobs ORDER BY created_at DESC, id DESC")
    else:
        rows = _sql_fetchall("SELECT * FROM fine_tuning_jobs ORDER BY created_at DESC, id DESC")
    jobs = [_decode_ft_row(r) for r in rows]
    if after:
        idx = next((i for i, j in enumerate(jobs) if j.get("id") == after), -1)
        if idx >= 0:
            jobs = jobs[idx + 1:]
    return jobs[: max(1, int(limit))]


def update_fine_tuning_job(job_id: str, **fields) -> bool:
    if not fields:
        return False
    allowed = {
        "finished_at", "fine_tuned_model", "status", "trained_tokens", "error", "result_files", "hyperparameters"
    }
    patch = {k: v for k, v in fields.items() if k in allowed}
    if not patch:
        return False
    if "error" in patch and patch["error"] is not None:
        patch["error"] = json.dumps(patch["error"])
    if "result_files" in patch and patch["result_files"] is not None:
        patch["result_files"] = json.dumps(patch["result_files"])
    if "hyperparameters" in patch and patch["hyperparameters"] is not None:
        patch["hyperparameters"] = json.dumps(patch["hyperparameters"])

    keys = list(patch.keys())
    if isinstance(_backend, SQLiteBackend):
        set_sql = ", ".join(f"{k}=?" for k in keys)
        params = tuple(patch[k] for k in keys) + (job_id,)
        changed = _sql_execute(f"UPDATE fine_tuning_jobs SET {set_sql} WHERE id=?", params)
    else:
        set_sql = ", ".join(f"{k}=%s" for k in keys)
        params = tuple(patch[k] for k in keys) + (job_id,)
        changed = _sql_execute(f"UPDATE fine_tuning_jobs SET {set_sql} WHERE id=%s", params)
    return changed > 0


def create_fine_tuning_job_event(job_id: str, message: str, level: str = "info", data: dict | None = None) -> str:
    import uuid as _uuid

    event_id = "ftevt-" + _uuid.uuid4().hex[:12]
    ts = int(time.time())
    payload = json.dumps(data or {})
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO fine_tuning_job_events(id, job_id, created_at, level, message, data) VALUES(?,?,?,?,?,?)",
            (event_id, job_id, ts, level, message, payload),
        )
    else:
        _sql_execute(
            "INSERT INTO fine_tuning_job_events(id, job_id, created_at, level, message, data) VALUES(%s,%s,%s,%s,%s,%s)",
            (event_id, job_id, ts, level, message, payload),
        )
    return event_id


def list_fine_tuning_job_events(job_id: str, limit: int = 100) -> list[dict]:
    safe_limit = max(1, min(int(limit), 1000))
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall(
            "SELECT * FROM fine_tuning_job_events WHERE job_id=? ORDER BY created_at ASC LIMIT ?",
            (job_id, safe_limit),
        )
    else:
        rows = _sql_fetchall(
            "SELECT * FROM fine_tuning_job_events WHERE job_id=%s ORDER BY created_at ASC LIMIT %s",
            (job_id, safe_limit),
        )

    events = []
    for row in rows:
        item = dict(row)
        raw_data = item.get("data")
        if isinstance(raw_data, str) and raw_data:
            try:
                item["data"] = json.loads(raw_data)
            except Exception:
                item["data"] = {}
        else:
            item["data"] = {}
        events.append(item)
    return events


def get_feedback_stats() -> dict:
    rows = load_feedback_export(limit=20000)
    up = sum(1 for r in rows if str(r.get("reaction")) == "thumbs_up")
    down = sum(1 for r in rows if str(r.get("reaction")) == "thumbs_down")
    return {"thumbs_up": up, "thumbs_down": down, "total": len(rows)}


def create_hitl_approval(approval_id: str, session_id: str, action: dict,
                         signature: str, created_at: str, updated_at: str):
    approvals = _load_json_pref("hitl_approvals", [])
    approvals = [a for a in approvals if a.get("id") != approval_id]
    approvals.append(
        {
            "id": approval_id,
            "session_id": session_id,
            "action": dict(action or {}),
            "signature": signature,
            "status": "pending",
            "note": "",
            "created_at": created_at,
            "updated_at": updated_at,
        }
    )
    _save_json_pref("hitl_approvals", approvals)


def list_hitl_approvals(session_id: str = "") -> list[dict]:
    approvals = _load_json_pref("hitl_approvals", [])
    if not isinstance(approvals, list):
        return []
    items = approvals
    if session_id:
        items = [a for a in items if str(a.get("session_id") or "") == session_id]
    return sorted(items, key=lambda a: str(a.get("created_at") or ""), reverse=True)


def load_hitl_approval(approval_id: str) -> dict | None:
    for approval in list_hitl_approvals():
        if approval.get("id") == approval_id:
            return dict(approval)
    return None


def update_hitl_approval_decision(approval_id: str, status: str, note: str, updated_at: str) -> dict | None:
    approvals = _load_json_pref("hitl_approvals", [])
    if not isinstance(approvals, list):
        return None
    updated = None
    for approval in approvals:
        if approval.get("id") == approval_id:
            approval["status"] = status
            approval["note"] = note
            approval["updated_at"] = updated_at
            updated = dict(approval)
            break
    _save_json_pref("hitl_approvals", approvals)
    return updated


def consume_hitl_approval(approval_id: str, updated_at: str) -> dict | None:
    return update_hitl_approval_decision(approval_id, "consumed", "", updated_at)


def clear_hitl_approvals():
    _save_json_pref("hitl_approvals", [])

# Note: More functions from original db.py would need to be added to the interface
# and both backends for full parity. This is the foundation.


# ─────────────────────────────────────────────────────────────────────────────
# Execution traces persistence
# ─────────────────────────────────────────────────────────────────────────────

import time as _time


def save_execution_trace(trace_id: str, events: list) -> None:
    now = _time.time()
    events_json = json.dumps(events)
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO execution_traces(trace_id, events, created_at, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(trace_id) DO UPDATE SET events=excluded.events, updated_at=excluded.updated_at",
            (trace_id, events_json, now, now),
        )
    else:
        _sql_execute(
            "INSERT INTO execution_traces(trace_id, events, created_at, updated_at) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(trace_id) DO UPDATE SET events=EXCLUDED.events, updated_at=EXCLUDED.updated_at",
            (trace_id, events_json, now, now),
        )


def load_execution_trace(trace_id: str) -> list | None:
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall("SELECT events FROM execution_traces WHERE trace_id=?", (trace_id,))
    else:
        rows = _sql_fetchall("SELECT events FROM execution_traces WHERE trace_id=%s", (trace_id,))
    if not rows:
        return None
    return json.loads(rows[0]["events"])


def list_execution_traces(limit: int = 50) -> list[dict]:
    rows = _sql_fetchall(
        "SELECT trace_id, created_at, updated_at FROM execution_traces ORDER BY updated_at DESC LIMIT "
        + str(int(limit))
    )
    return list(rows)


def delete_execution_trace(trace_id: str) -> bool:
    if isinstance(_backend, SQLiteBackend):
        changed = _sql_execute("DELETE FROM execution_traces WHERE trace_id=?", (trace_id,))
    else:
        changed = _sql_execute("DELETE FROM execution_traces WHERE trace_id=%s", (trace_id,))
    return changed > 0


# ─────────────────────────────────────────────────────────────────────────────
# Autonomy traces persistence
# ─────────────────────────────────────────────────────────────────────────────


def save_autonomy_trace(trace_id: str, data: dict) -> None:
    now = _time.time()
    data_json = json.dumps(data)
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO autonomy_traces(trace_id, data, created_at, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(trace_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (trace_id, data_json, now, now),
        )
    else:
        _sql_execute(
            "INSERT INTO autonomy_traces(trace_id, data, created_at, updated_at) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(trace_id) DO UPDATE SET data=EXCLUDED.data, updated_at=EXCLUDED.updated_at",
            (trace_id, data_json, now, now),
        )


def load_autonomy_trace(trace_id: str) -> dict | None:
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall("SELECT data FROM autonomy_traces WHERE trace_id=?", (trace_id,))
    else:
        rows = _sql_fetchall("SELECT data FROM autonomy_traces WHERE trace_id=%s", (trace_id,))
    if not rows:
        return None
    return json.loads(rows[0]["data"])


# ─────────────────────────────────────────────────────────────────────────────
# Task queue shared memory persistence
# ─────────────────────────────────────────────────────────────────────────────


def db_set_shared_memory(key: str, value) -> None:
    now = _time.time()
    value_json = json.dumps(value)
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO task_shared_memory(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value_json, now),
        )
    else:
        _sql_execute(
            "INSERT INTO task_shared_memory(key, value, updated_at) VALUES(%s,%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            (key, value_json, now),
        )


def db_get_shared_memory(key: str):
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall("SELECT value FROM task_shared_memory WHERE key=?", (key,))
    else:
        rows = _sql_fetchall("SELECT value FROM task_shared_memory WHERE key=%s", (key,))
    if not rows:
        return None
    return json.loads(rows[0]["value"])


def db_delete_shared_memory(key: str) -> bool:
    if isinstance(_backend, SQLiteBackend):
        changed = _sql_execute("DELETE FROM task_shared_memory WHERE key=?", (key,))
    else:
        changed = _sql_execute("DELETE FROM task_shared_memory WHERE key=%s", (key,))
    return changed > 0


def db_list_shared_memory() -> dict:
    rows = _sql_fetchall("SELECT key, value FROM task_shared_memory ORDER BY key")
    return {r["key"]: json.loads(r["value"]) for r in rows}


# ─────────────────────────────────────────────────────────────────────────────
# Task queue job persistence
# ─────────────────────────────────────────────────────────────────────────────


def db_save_task_job(task_id: str, description: str, priority: int, dependencies: list,
                     metadata: dict, schedule_cron: str, status: str, result: str,
                     error: str, created_at: float, started_at=None, finished_at=None) -> None:
    deps_json = json.dumps(dependencies)
    meta_json = json.dumps(metadata)
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO task_queue_jobs(task_id, description, priority, dependencies, metadata, "
            "schedule_cron, status, result, error, created_at, started_at, finished_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(task_id) DO UPDATE SET status=excluded.status, result=excluded.result, "
            "error=excluded.error, started_at=excluded.started_at, finished_at=excluded.finished_at, "
            "metadata=excluded.metadata",
            (task_id, description, priority, deps_json, meta_json, schedule_cron, status,
             result, error, created_at, started_at, finished_at),
        )
    else:
        _sql_execute(
            "INSERT INTO task_queue_jobs(task_id, description, priority, dependencies, metadata, "
            "schedule_cron, status, result, error, created_at, started_at, finished_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(task_id) DO UPDATE SET status=EXCLUDED.status, result=EXCLUDED.result, "
            "error=EXCLUDED.error, started_at=EXCLUDED.started_at, finished_at=EXCLUDED.finished_at, "
            "metadata=EXCLUDED.metadata",
            (task_id, description, priority, deps_json, meta_json, schedule_cron, status,
             result, error, created_at, started_at, finished_at),
        )


def db_list_task_jobs(status: str = "", limit: int = 50) -> list[dict]:
    if status:
        if isinstance(_backend, SQLiteBackend):
            rows = _sql_fetchall(
                "SELECT * FROM task_queue_jobs WHERE status=? ORDER BY created_at DESC LIMIT " + str(int(limit)),
                (status,),
            )
        else:
            rows = _sql_fetchall(
                "SELECT * FROM task_queue_jobs WHERE status=%s ORDER BY created_at DESC LIMIT " + str(int(limit)),
                (status,),
            )
    else:
        rows = _sql_fetchall(
            "SELECT * FROM task_queue_jobs ORDER BY created_at DESC LIMIT " + str(int(limit))
        )
    result = []
    for r in rows:
        d = dict(r)
        d["dependencies"] = json.loads(d.get("dependencies") or "[]")
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        result.append(d)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Fine-tuning training samples (reflection → fine-tuning pipeline)
# ─────────────────────────────────────────────────────────────────────────────


def save_ft_training_sample(task: str, result: str, quality: float,
                             lessons: list, source: str = "reflection") -> str:
    import uuid as _uuid
    sample_id = "fts-" + _uuid.uuid4().hex[:12]
    now = _time.time()
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO ft_training_samples(id, created_at, task, result, quality, lessons, source) "
            "VALUES(?,?,?,?,?,?,?)",
            (sample_id, now, task, result, quality, json.dumps(lessons), source),
        )
    else:
        _sql_execute(
            "INSERT INTO ft_training_samples(id, created_at, task, result, quality, lessons, source) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (sample_id, now, task, result, quality, json.dumps(lessons), source),
        )
    return sample_id


def list_ft_training_samples(limit: int = 100, min_quality: float = 0.0) -> list[dict]:
    if isinstance(_backend, SQLiteBackend):
        rows = _sql_fetchall(
            "SELECT * FROM ft_training_samples WHERE quality >= ? ORDER BY created_at DESC LIMIT " + str(int(limit)),
            (min_quality,),
        )
    else:
        rows = _sql_fetchall(
            "SELECT * FROM ft_training_samples WHERE quality >= %s ORDER BY created_at DESC LIMIT " + str(int(limit)),
            (min_quality,),
        )
    result = []
    for r in rows:
        d = dict(r)
        d["lessons"] = json.loads(d.get("lessons") or "[]")
        result.append(d)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Fine-tuning adapter/version registry + dataset provenance + RLHF/DPO jobs
# ─────────────────────────────────────────────────────────────────────────────


def _ft_adapters_key() -> str:
    return "ft.adapters.v1"


def _ft_adapter_active_key() -> str:
    return "ft.adapters.active.v1"


def _ft_dataset_versions_key() -> str:
    return "ft.dataset_versions.v1"


def _ft_rlhf_dpo_jobs_key() -> str:
    return "ft.rlhf_dpo_jobs.v1"


def _ft_distill_jobs_key() -> str:
    return "ft.distill_jobs.v1"


def _ft_multitask_adapter_map_key() -> str:
    return "ft.multitask_adapter_map.v1"


def _ft_sample_curation_key() -> str:
    return "ft.sample_curation.v1"


def _ft_synthetic_batches_key() -> str:
    return "ft.synthetic_batches.v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def save_lora_adapter_version(
    adapter_id: str,
    version: str,
    base_model: str,
    checkpoint_uri: str,
    metrics: dict | None = None,
    provenance: dict | None = None,
    tags: list | None = None,
    status: str = "ready",
) -> dict:
    adapters = _load_json_pref(_ft_adapters_key(), [])
    rec = {
        "adapter_id": str(adapter_id).strip(),
        "version": str(version).strip(),
        "base_model": str(base_model).strip(),
        "checkpoint_uri": str(checkpoint_uri).strip(),
        "metrics": dict(metrics or {}),
        "provenance": dict(provenance or {}),
        "tags": [str(t) for t in (tags or [])],
        "status": str(status or "ready"),
        "created_at": _now_iso(),
    }
    adapters = [
        a
        for a in adapters
        if not (
            str(a.get("adapter_id") or "") == rec["adapter_id"]
            and str(a.get("version") or "") == rec["version"]
        )
    ]
    adapters.append(rec)
    _save_json_pref(_ft_adapters_key(), adapters[-5000:])
    return rec


def list_lora_adapter_versions(adapter_id: str = "") -> list[dict]:
    adapters = _load_json_pref(_ft_adapters_key(), [])
    if adapter_id:
        adapters = [a for a in adapters if str(a.get("adapter_id") or "") == str(adapter_id)]
    adapters.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
    return adapters


def get_lora_adapter_version(adapter_id: str, version: str = "") -> dict | None:
    rows = list_lora_adapter_versions(adapter_id=adapter_id)
    if not rows:
        return None
    if not version:
        return rows[0]
    for row in rows:
        if str(row.get("version") or "") == str(version):
            return row
    return None


def compare_lora_adapter_versions(adapter_id: str, left_version: str, right_version: str) -> dict | None:
    left = get_lora_adapter_version(adapter_id, left_version)
    right = get_lora_adapter_version(adapter_id, right_version)
    if left is None or right is None:
        return None

    left_metrics = left.get("metrics") if isinstance(left.get("metrics"), dict) else {}
    right_metrics = right.get("metrics") if isinstance(right.get("metrics"), dict) else {}
    keys = sorted(set(left_metrics.keys()) | set(right_metrics.keys()))
    deltas = {}
    for key in keys:
        lv = left_metrics.get(key)
        rv = right_metrics.get(key)
        if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
            deltas[key] = round(float(rv) - float(lv), 6)

    return {
        "adapter_id": adapter_id,
        "left": left,
        "right": right,
        "metric_delta": deltas,
    }


def set_active_lora_adapter(adapter_id: str, version: str, target_model: str = "") -> dict:
    active = {
        "adapter_id": str(adapter_id).strip(),
        "version": str(version).strip(),
        "target_model": str(target_model or "").strip(),
        "activated_at": _now_iso(),
    }
    _save_json_pref(_ft_adapter_active_key(), active)
    return active


def get_active_lora_adapter() -> dict:
    active = _load_json_pref(_ft_adapter_active_key(), {})
    if not isinstance(active, dict):
        return {}
    return active


def save_ft_dataset_version(
    dataset_id: str,
    source: str,
    fmt: str,
    row_count: int,
    provenance: dict | None = None,
    checksum: str = "",
) -> dict:
    versions = _load_json_pref(_ft_dataset_versions_key(), [])
    rec = {
        "dataset_id": str(dataset_id).strip(),
        "source": str(source or "feedback").strip(),
        "format": str(fmt or "jsonl").strip(),
        "row_count": int(row_count),
        "provenance": dict(provenance or {}),
        "checksum": str(checksum or ""),
        "created_at": _now_iso(),
    }
    versions = [v for v in versions if str(v.get("dataset_id") or "") != rec["dataset_id"]]
    versions.append(rec)
    _save_json_pref(_ft_dataset_versions_key(), versions[-5000:])
    return rec


def list_ft_dataset_versions(limit: int = 100) -> list[dict]:
    rows = _load_json_pref(_ft_dataset_versions_key(), [])
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[: max(1, int(limit))]


def get_ft_dataset_version(dataset_id: str) -> dict | None:
    for row in list_ft_dataset_versions(limit=10000):
        if str(row.get("dataset_id") or "") == str(dataset_id):
            return row
    return None


def create_rlhf_dpo_job(
    method: str,
    base_model: str,
    dataset_version_id: str,
    config: dict | None = None,
) -> dict:
    import uuid as _uuid

    jobs = _load_json_pref(_ft_rlhf_dpo_jobs_key(), [])
    job = {
        "id": f"rdj-{_uuid.uuid4().hex[:12]}",
        "method": str(method or "dpo").lower(),
        "base_model": str(base_model or "nexus-prime-base").strip(),
        "dataset_version_id": str(dataset_version_id or "").strip(),
        "config": dict(config or {}),
        "status": "queued",
        "events": [],
        "result": {},
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    jobs.append(job)
    _save_json_pref(_ft_rlhf_dpo_jobs_key(), jobs[-5000:])
    return job


def list_rlhf_dpo_jobs(limit: int = 100) -> list[dict]:
    rows = _load_json_pref(_ft_rlhf_dpo_jobs_key(), [])
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[: max(1, int(limit))]


def get_rlhf_dpo_job(job_id: str) -> dict | None:
    rows = _load_json_pref(_ft_rlhf_dpo_jobs_key(), [])
    for row in rows:
        if str(row.get("id") or "") == str(job_id):
            return row
    return None


def update_rlhf_dpo_job(job_id: str, **fields) -> dict | None:
    jobs = _load_json_pref(_ft_rlhf_dpo_jobs_key(), [])
    updated = None
    for idx, row in enumerate(jobs):
        if str(row.get("id") or "") != str(job_id):
            continue
        merged = dict(row)
        for key, value in fields.items():
            merged[key] = value
        merged["updated_at"] = _now_iso()
        jobs[idx] = merged
        updated = merged
        break
    if updated is None:
        return None
    _save_json_pref(_ft_rlhf_dpo_jobs_key(), jobs[-5000:])
    return updated


def append_rlhf_dpo_job_event(
    job_id: str,
    message: str,
    level: str = "info",
    data: dict | None = None,
) -> dict | None:
    jobs = _load_json_pref(_ft_rlhf_dpo_jobs_key(), [])
    updated = None
    for idx, row in enumerate(jobs):
        if str(row.get("id") or "") != str(job_id):
            continue
        merged = dict(row)
        events = merged.get("events") if isinstance(merged.get("events"), list) else []
        events.append(
            {
                "id": f"rde-{uuid.uuid4().hex[:10]}",
                "created_at": _now_iso(),
                "level": str(level or "info"),
                "message": str(message or ""),
                "data": dict(data or {}),
            }
        )
        merged["events"] = events[-500:]
        merged["updated_at"] = _now_iso()
        jobs[idx] = merged
        updated = merged
        break
    if updated is None:
        return None
    _save_json_pref(_ft_rlhf_dpo_jobs_key(), jobs[-5000:])
    return updated


def create_distill_job(
    teacher_model: str,
    student_model: str,
    provider: str,
    config: dict | None = None,
) -> dict:
    jobs = _load_json_pref(_ft_distill_jobs_key(), [])
    job = {
        "id": f"dsj-{uuid.uuid4().hex[:12]}",
        "teacher_model": str(teacher_model or "").strip(),
        "student_model": str(student_model or "").strip(),
        "provider": str(provider or "auto").strip(),
        "config": dict(config or {}),
        "status": "queued",
        "events": [],
        "result": {},
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    jobs.append(job)
    _save_json_pref(_ft_distill_jobs_key(), jobs[-5000:])
    return job


def list_distill_jobs(limit: int = 100) -> list[dict]:
    rows = _load_json_pref(_ft_distill_jobs_key(), [])
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[: max(1, int(limit))]


def get_distill_job(job_id: str) -> dict | None:
    for row in _load_json_pref(_ft_distill_jobs_key(), []):
        if str(row.get("id") or "") == str(job_id):
            return row
    return None


def update_distill_job(job_id: str, **fields) -> dict | None:
    jobs = _load_json_pref(_ft_distill_jobs_key(), [])
    updated = None
    for idx, row in enumerate(jobs):
        if str(row.get("id") or "") != str(job_id):
            continue
        merged = dict(row)
        for key, value in fields.items():
            merged[key] = value
        merged["updated_at"] = _now_iso()
        jobs[idx] = merged
        updated = merged
        break
    if updated is None:
        return None
    _save_json_pref(_ft_distill_jobs_key(), jobs[-5000:])
    return updated


def append_distill_job_event(
    job_id: str,
    message: str,
    level: str = "info",
    data: dict | None = None,
) -> dict | None:
    jobs = _load_json_pref(_ft_distill_jobs_key(), [])
    updated = None
    for idx, row in enumerate(jobs):
        if str(row.get("id") or "") != str(job_id):
            continue
        merged = dict(row)
        events = merged.get("events") if isinstance(merged.get("events"), list) else []
        events.append(
            {
                "id": f"dse-{uuid.uuid4().hex[:10]}",
                "created_at": _now_iso(),
                "level": str(level or "info"),
                "message": str(message or ""),
                "data": dict(data or {}),
            }
        )
        merged["events"] = events[-500:]
        merged["updated_at"] = _now_iso()
        jobs[idx] = merged
        updated = merged
        break
    if updated is None:
        return None
    _save_json_pref(_ft_distill_jobs_key(), jobs[-5000:])
    return updated


def save_multitask_adapter_map(mapping: dict[str, dict]) -> dict:
    normalized: dict[str, dict] = {}
    for task_name, rec in (mapping or {}).items():
        key = str(task_name or "").strip().lower()
        if not key:
            continue
        row = rec if isinstance(rec, dict) else {}
        normalized[key] = {
            "adapter_id": str(row.get("adapter_id") or "").strip(),
            "version": str(row.get("version") or "").strip(),
            "target_model": str(row.get("target_model") or "").strip(),
            "updated_at": _now_iso(),
        }
    payload = {"mapping": normalized, "updated_at": _now_iso()}
    _save_json_pref(_ft_multitask_adapter_map_key(), payload)
    return payload


def get_multitask_adapter_map() -> dict:
    row = _load_json_pref(_ft_multitask_adapter_map_key(), {})
    if not isinstance(row, dict):
        return {"mapping": {}, "updated_at": ""}
    mapping = row.get("mapping") if isinstance(row.get("mapping"), dict) else {}
    return {"mapping": mapping, "updated_at": str(row.get("updated_at") or "")}


def upsert_ft_sample_curation(
    sample_id: str,
    approved: bool | None = None,
    label: str = "",
    notes: str = "",
    reviewer: str = "system",
) -> dict:
    data = _load_json_pref(_ft_sample_curation_key(), {})
    if not isinstance(data, dict):
        data = {}
    row = data.get(sample_id) if isinstance(data.get(sample_id), dict) else {}
    rec = dict(row)
    rec["sample_id"] = str(sample_id or "").strip()
    if approved is not None:
        rec["approved"] = bool(approved)
    if label.strip():
        rec["label"] = label.strip()
    if notes.strip():
        rec["notes"] = notes.strip()
    rec["reviewer"] = str(reviewer or "system")
    rec["updated_at"] = _now_iso()
    data[rec["sample_id"]] = rec
    _save_json_pref(_ft_sample_curation_key(), data)
    return rec


def get_ft_sample_curation(sample_id: str) -> dict | None:
    data = _load_json_pref(_ft_sample_curation_key(), {})
    if not isinstance(data, dict):
        return None
    row = data.get(sample_id)
    return row if isinstance(row, dict) else None


def list_ft_sample_curation() -> dict[str, dict]:
    data = _load_json_pref(_ft_sample_curation_key(), {})
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def save_synthetic_batch(
    batch_id: str,
    topic: str,
    row_count: int,
    params: dict | None = None,
    dataset_id: str = "",
    source: str = "agent_swarm",
) -> dict:
    rows = _load_json_pref(_ft_synthetic_batches_key(), [])
    rec = {
        "batch_id": str(batch_id or "").strip(),
        "topic": str(topic or "").strip(),
        "row_count": int(row_count),
        "source": str(source or "agent_swarm").strip(),
        "dataset_id": str(dataset_id or "").strip(),
        "params": dict(params or {}),
        "created_at": _now_iso(),
    }
    rows = [r for r in rows if str(r.get("batch_id") or "") != rec["batch_id"]]
    rows.append(rec)
    _save_json_pref(_ft_synthetic_batches_key(), rows[-2000:])
    return rec


def list_synthetic_batches(limit: int = 100) -> list[dict]:
    rows = _load_json_pref(_ft_synthetic_batches_key(), [])
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[: max(1, int(limit))]


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────

import time as _time_module


def write_audit_entry(
    actor: str,
    action: str,
    resource: str = "",
    result: str = "ok",
    metadata: dict | None = None,
    request_id: str = "",
) -> None:
    import json as _json
    import time as _t
    params = (
        _t.time(),
        actor,
        action,
        resource,
        result,
        _json.dumps(metadata or {}),
        request_id,
    )
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO audit_log(ts,actor,action,resource,result,metadata,request_id)"
            " VALUES(?,?,?,?,?,?,?)",
            params,
        )
    else:
        _sql_execute(
            "INSERT INTO audit_log(ts,actor,action,resource,result,metadata,request_id)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s)",
            params,
        )


def list_audit_log(limit: int = 100, actor: str = "", action: str = "") -> list[dict]:
    import json as _json
    conditions: list[str] = []
    params: list = []
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    if actor:
        conditions.append(f"actor={ph}")
        params.append(actor)
    if action:
        conditions.append(f"action={ph}")
        params.append(action)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = _sql_fetchall(
        f"SELECT * FROM audit_log {where} ORDER BY ts DESC LIMIT {int(limit)}",
        tuple(params),
    )
    result = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json.loads(d.get("metadata") or "{}")
        result.append(d)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Feature flags
# ─────────────────────────────────────────────────────────────────────────────

def upsert_feature_flag(
    name: str,
    enabled: bool,
    description: str = "",
    rollout_percentage: int = 0,
    user_overrides: str = "{}",
    org_overrides: str = "{}",
    value: str = "",
) -> dict:
    import time as _t
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    now = _t.time()
    params = (
        name, int(enabled), description, int(rollout_percentage),
        user_overrides, org_overrides, value, now,
    )
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO feature_flags(name,enabled,description,rollout_percentage,"
            "user_overrides,org_overrides,value,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET"
            " enabled=excluded.enabled, description=excluded.description,"
            " rollout_percentage=excluded.rollout_percentage,"
            " user_overrides=excluded.user_overrides, org_overrides=excluded.org_overrides,"
            " value=excluded.value, updated_at=excluded.updated_at",
            params,
        )
    else:
        _sql_execute(
            "INSERT INTO feature_flags(name,enabled,description,rollout_percentage,"
            "user_overrides,org_overrides,value,updated_at)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT(name) DO UPDATE SET"
            " enabled=EXCLUDED.enabled, description=EXCLUDED.description,"
            " rollout_percentage=EXCLUDED.rollout_percentage,"
            " user_overrides=EXCLUDED.user_overrides, org_overrides=EXCLUDED.org_overrides,"
            " value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            params,
        )
    return load_feature_flag(name) or {"name": name}


def load_feature_flag(name: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(f"SELECT * FROM feature_flags WHERE name={ph}", (name,))
    return dict(rows[0]) if rows else None


def list_feature_flags() -> list[dict]:
    return [dict(r) for r in _sql_fetchall("SELECT * FROM feature_flags ORDER BY name")]


def delete_feature_flag(name: str) -> bool:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    n = _sql_execute(f"DELETE FROM feature_flags WHERE name={ph}", (name,))
    return n > 0


# ─────────────────────────────────────────────────────────────────────────────
# Login attempts (brute-force detection)
# ─────────────────────────────────────────────────────────────────────────────

def record_login_attempt(username: str, ip_address: str = "", success: bool = False) -> None:
    import time as _t
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(
        f"INSERT INTO login_attempts(username,ip_address,success,ts) VALUES({ph},{ph},{ph},{ph})",
        (username, ip_address, int(success), _t.time()),
    )


def count_recent_failures(username: str, window_seconds: int = 900) -> int:
    import time as _t
    cutoff = _t.time() - window_seconds
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(
        f"SELECT COUNT(*) as n FROM login_attempts"
        f" WHERE username={ph} AND success=0 AND ts>{ph}",
        (username, cutoff),
    )
    return int(rows[0]["n"]) if rows else 0


def clear_login_attempts(username: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(f"DELETE FROM login_attempts WHERE username={ph}", (username,))


# ─────────────────────────────────────────────────────────────────────────────
# MFA
# ─────────────────────────────────────────────────────────────────────────────

def save_mfa_secret(username: str, secret: str) -> None:
    import time as _t
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO mfa_secrets(username,secret,enabled,created_at) VALUES(?,?,0,?)"
            " ON CONFLICT(username) DO UPDATE SET secret=excluded.secret,"
            " enabled=0, created_at=excluded.created_at",
            (username, secret, _t.time()),
        )
    else:
        _sql_execute(
            "INSERT INTO mfa_secrets(username,secret,enabled,created_at) VALUES(%s,%s,0,%s)"
            " ON CONFLICT(username) DO UPDATE SET secret=EXCLUDED.secret,"
            " enabled=0, created_at=EXCLUDED.created_at",
            (username, secret, _t.time()),
        )


def get_mfa_secret(username: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(f"SELECT * FROM mfa_secrets WHERE username={ph}", (username,))
    return dict(rows[0]) if rows else None


def enable_mfa(username: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(f"UPDATE mfa_secrets SET enabled=1 WHERE username={ph}", (username,))


def disable_mfa(username: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(f"UPDATE mfa_secrets SET enabled=0 WHERE username={ph}", (username,))
    _sql_execute(f"DELETE FROM mfa_recovery_codes WHERE username={ph}", (username,))


def save_mfa_recovery_codes(username: str, code_hashes: list[str]) -> None:
    import time as _t
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(f"DELETE FROM mfa_recovery_codes WHERE username={ph}", (username,))
    for code_hash in code_hashes:
        _sql_execute(
            f"INSERT INTO mfa_recovery_codes(username,code_hash,used,created_at)"
            f" VALUES({ph},{ph},0,{ph})",
            (username, code_hash, _t.time()),
        )


def use_mfa_recovery_code(username: str, code_hash: str) -> bool:
    """Mark a recovery code as used. Returns True if it existed and was unused."""
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(
        f"SELECT id FROM mfa_recovery_codes WHERE username={ph} AND code_hash={ph} AND used=0",
        (username, code_hash),
    )
    if not rows:
        return False
    _sql_execute(
        f"UPDATE mfa_recovery_codes SET used=1 WHERE id={ph}",
        (rows[0]["id"],),
    )
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Trusted devices
# ─────────────────────────────────────────────────────────────────────────────

def save_trusted_device(username: str, device_hash: str, label: str = "") -> None:
    import time as _t
    now = _t.time()
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO trusted_devices(username,device_hash,label,created_at,last_seen)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(username,device_hash) DO UPDATE SET last_seen=excluded.last_seen",
            (username, device_hash, label, now, now),
        )
    else:
        _sql_execute(
            "INSERT INTO trusted_devices(username,device_hash,label,created_at,last_seen)"
            " VALUES(%s,%s,%s,%s,%s)"
            " ON CONFLICT(username,device_hash) DO UPDATE SET last_seen=EXCLUDED.last_seen",
            (username, device_hash, label, now, now),
        )


def is_trusted_device(username: str, device_hash: str) -> bool:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(
        f"SELECT id FROM trusted_devices WHERE username={ph} AND device_hash={ph}",
        (username, device_hash),
    )
    return bool(rows)


def remove_trusted_device(username: str, device_hash: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(
        f"DELETE FROM trusted_devices WHERE username={ph} AND device_hash={ph}",
        (username, device_hash),
    )


def list_trusted_devices(username: str) -> list[dict]:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    return [dict(r) for r in _sql_fetchall(
        f"SELECT * FROM trusted_devices WHERE username={ph} ORDER BY last_seen DESC",
        (username,),
    )]


# ─────────────────────────────────────────────────────────────────────────────
# Org CRUD (called from src/orgs.py)
# ─────────────────────────────────────────────────────────────────────────────

def db_create_org(
    name: str,
    owner: str,
    plan: str = "free",
    metadata: str = "{}",
) -> dict:
    import uuid as _uuid, time as _t
    org_id = "org-" + _uuid.uuid4().hex[:12]
    now = _t.time()
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO orgs(id,name,owner,plan,metadata,tokens_per_day,spend_cap_usd,created_at,updated_at)"
            " VALUES(?,?,?,?,?,0,0,?,?)",
            (org_id, name, owner, plan, metadata, now, now),
        )
    else:
        _sql_execute(
            "INSERT INTO orgs(id,name,owner,plan,metadata,tokens_per_day,spend_cap_usd,created_at,updated_at)"
            " VALUES(%s,%s,%s,%s,%s,0,0,%s,%s)",
            (org_id, name, owner, plan, metadata, now, now),
        )
    return db_get_org(org_id) or {"id": org_id}


def db_get_org(org_id: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(f"SELECT * FROM orgs WHERE id={ph}", (org_id,))
    return dict(rows[0]) if rows else None


def db_get_org_by_name(name: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(f"SELECT * FROM orgs WHERE name={ph} LIMIT 1", (name,))
    return dict(rows[0]) if rows else None


def db_list_orgs(owner: str = "", limit: int = 100) -> list[dict]:
    if owner:
        ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
        return [dict(r) for r in _sql_fetchall(
            f"SELECT * FROM orgs WHERE owner={ph} ORDER BY created_at DESC LIMIT {int(limit)}",
            (owner,),
        )]
    return [dict(r) for r in _sql_fetchall(
        f"SELECT * FROM orgs ORDER BY created_at DESC LIMIT {int(limit)}"
    )]


def db_update_org(org_id: str, **fields) -> dict | None:
    import time as _t
    if not fields:
        return db_get_org(org_id)
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    fields["updated_at"] = _t.time()
    set_clause = ", ".join(f"{k}={ph}" for k in fields)
    values = list(fields.values()) + [org_id]
    _sql_execute(f"UPDATE orgs SET {set_clause} WHERE id={ph}", tuple(values))
    return db_get_org(org_id)


def db_delete_org(org_id: str) -> bool:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    n = _sql_execute(f"DELETE FROM orgs WHERE id={ph}", (org_id,))
    return n > 0


def db_add_org_member(org_id: str, username: str, role: str = "member") -> dict:
    import time as _t
    now = _t.time()
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO org_members(org_id,username,role,joined_at) VALUES(?,?,?,?)"
            " ON CONFLICT(org_id,username) DO UPDATE SET role=excluded.role",
            (org_id, username, role, now),
        )
    else:
        _sql_execute(
            "INSERT INTO org_members(org_id,username,role,joined_at) VALUES(%s,%s,%s,%s)"
            " ON CONFLICT(org_id,username) DO UPDATE SET role=EXCLUDED.role",
            (org_id, username, role, now),
        )
    return {"org_id": org_id, "username": username, "role": role, "joined_at": now}


def db_remove_org_member(org_id: str, username: str) -> bool:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    n = _sql_execute(
        f"DELETE FROM org_members WHERE org_id={ph} AND username={ph}",
        (org_id, username),
    )
    return n > 0


def db_update_org_member_role(org_id: str, username: str, role: str) -> bool:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    n = _sql_execute(
        f"UPDATE org_members SET role={ph} WHERE org_id={ph} AND username={ph}",
        (role, org_id, username),
    )
    return n > 0


def db_get_org_member(org_id: str, username: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(
        f"SELECT * FROM org_members WHERE org_id={ph} AND username={ph}",
        (org_id, username),
    )
    return dict(rows[0]) if rows else None


def db_list_org_members(org_id: str) -> list[dict]:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    return [dict(r) for r in _sql_fetchall(
        f"SELECT * FROM org_members WHERE org_id={ph} ORDER BY joined_at DESC",
        (org_id,),
    )]


def db_delete_org_members(org_id: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(f"DELETE FROM org_members WHERE org_id={ph}", (org_id,))


def db_get_user_orgs(username: str) -> list[dict]:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    return [dict(r) for r in _sql_fetchall(
        f"SELECT m.org_id, m.role, m.joined_at, o.name, o.plan, o.owner"
        f" FROM org_members m JOIN orgs o ON m.org_id=o.id"
        f" WHERE m.username={ph} ORDER BY m.joined_at DESC",
        (username,),
    )]


def db_create_org_invite(
    org_id: str,
    token: str,
    invited_by: str,
    email: str = "",
    role: str = "member",
    expires_at: float = 0.0,
) -> dict:
    import time as _t
    now = _t.time()
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO org_invites(org_id,token,invited_by,email,role,expires_at,used,used_by,created_at)"
            " VALUES(?,?,?,?,?,?,0,'',?)",
            (org_id, token, invited_by, email, role, expires_at, now),
        )
    else:
        _sql_execute(
            "INSERT INTO org_invites(org_id,token,invited_by,email,role,expires_at,used,used_by,created_at)"
            " VALUES(%s,%s,%s,%s,%s,%s,0,'',%s)",
            (org_id, token, invited_by, email, role, expires_at, now),
        )
    return db_get_org_invite(token) or {"token": token, "org_id": org_id}


def db_get_org_invite(token: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(f"SELECT * FROM org_invites WHERE token={ph}", (token,))
    return dict(rows[0]) if rows else None


def db_list_org_invites(org_id: str, include_used: bool = False) -> list[dict]:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    if include_used:
        return [dict(r) for r in _sql_fetchall(
            f"SELECT * FROM org_invites WHERE org_id={ph} ORDER BY created_at DESC",
            (org_id,),
        )]
    return [dict(r) for r in _sql_fetchall(
        f"SELECT * FROM org_invites WHERE org_id={ph} AND used=0 ORDER BY created_at DESC",
        (org_id,),
    )]


def db_mark_invite_used(token: str, used_by: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(
        f"UPDATE org_invites SET used=1, used_by={ph} WHERE token={ph}",
        (used_by, token),
    )


def db_revoke_org_invite(token: str) -> bool:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    n = _sql_execute(f"DELETE FROM org_invites WHERE token={ph}", (token,))
    return n > 0


def db_delete_org_invites(org_id: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(f"DELETE FROM org_invites WHERE org_id={ph}", (org_id,))


# ─────────────────────────────────────────────────────────────────────────────
# GDPR / data deletion cascade
# ─────────────────────────────────────────────────────────────────────────────

def delete_user_data(username: str) -> dict[str, int]:
    """
    GDPR right-to-erasure: hard-delete all data for *username* across:
      DB tables → vector store (ChromaDB memory) → memory JSON store → RAG corpus
    Returns counts of deleted rows per store.
    """
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    results: dict[str, int] = {}

    # ── 1. Relational DB tables ────────────────────────────────────────────
    for table in ["auth_api_keys", "oauth_accounts", "mfa_secrets", "mfa_recovery_codes",
                  "login_attempts", "trusted_devices", "org_members", "webauthn_credentials",
                  "saml_sessions"]:
        try:
            n = _sql_execute(f"DELETE FROM {table} WHERE username={ph}", (username,))
            results[table] = n
        except Exception:
            pass
    # Chats have username column (added via online_ddl migration)
    try:
        n = _sql_execute(f"DELETE FROM chats WHERE username={ph}", (username,))
        results["chats"] = n
    except Exception:
        pass
    # API key audit rows
    try:
        n = _sql_execute(f"DELETE FROM api_key_audit WHERE username={ph}", (username,))
        results["api_key_audit"] = n
    except Exception:
        pass
    # Usage log rows
    try:
        n = _sql_execute(f"DELETE FROM usage_log WHERE username={ph}", (username,))
        results["usage_log"] = n
    except Exception:
        pass
    # Memory table (SQLite memory store)
    try:
        n = _sql_execute(f"DELETE FROM memory WHERE username={ph}", (username,))
        results["memory_table"] = n
    except Exception:
        pass
    # Delete the user account itself
    try:
        n = _sql_execute(f"DELETE FROM users WHERE username={ph}", (username,))
        results["users"] = n
    except Exception:
        pass

    # ── 2. Vector store (ChromaDB semantic memory) ─────────────────────────
    try:
        from .memory import _get_collection
        coll = _get_collection()
        if coll:
            # Delete all entries where metadata.username matches
            existing = coll.get(where={"username": {"$eq": username}})
            if existing and existing.get("ids"):
                coll.delete(ids=existing["ids"])
                results["chroma_memory"] = len(existing["ids"])
    except Exception:
        pass

    # ── 3. Memory JSON meta store (flat file per-entry metadata) ──────────
    try:
        from .memory import _load_meta, _save_meta
        meta = _load_meta()
        entries = meta.get("entries", {})
        before = len(entries)
        entries = {k: v for k, v in entries.items()
                   if str(v.get("username", "")) != username}
        meta["entries"] = entries
        _save_meta(meta)
        results["memory_meta"] = before - len(entries)
    except Exception:
        pass

    # ── 4. RAG corpus: delete documents ingested by this user ─────────────
    try:
        from .rag.vector_store import VectorStoreManager
        from .rag.rag_system import get_rag_system
        rag = get_rag_system()
        vs = rag.vector_store if hasattr(rag, "vector_store") else None
        if vs is not None:
            all_docs = vs.get_all_documents()
            user_doc_ids = [
                d["id"] for d in all_docs
                if str(d.get("metadata", {}).get("uploaded_by", "")) == username
            ]
            if user_doc_ids:
                vs.delete(user_doc_ids)
                results["rag_corpus"] = len(user_doc_ids)
    except Exception:
        pass

    return results


def export_org_data(org_id: str) -> dict:
    """Export all data associated with an org as a portable bundle."""
    org = db_get_org(org_id)
    if not org:
        return {}
    members = db_list_org_members(org_id)
    member_usernames = [str(m.get("username") or "") for m in members]
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    # Collect usage stats for all members
    usage_rows: list[dict] = []
    for uname in member_usernames:
        rows = _sql_fetchall(
            f"SELECT * FROM usage_log WHERE task_type LIKE {ph} LIMIT 1000",
            (f"%",),
        )
        usage_rows.extend(rows)
    # Collect chats belonging to members
    chats: list[dict] = []
    for uname in member_usernames:
        chat_rows = _sql_fetchall(
            f"SELECT id, title, created_at, updated_at FROM chats WHERE username={ph}",
            (uname,),
        )
        chats.extend(chat_rows)
    invites = db_list_org_invites(org_id, include_used=True)
    return {
        "org": org,
        "members": members,
        "invites": invites,
        "chats": chats,
        "export_at": datetime.now(timezone.utc).isoformat(),
    }


def delete_org_data(org_id: str) -> dict[str, int]:
    """
    Cascading GDPR deletion for an entire org.
    Deletes: org members' chats + usage + memory, org-scoped API keys, invites, org record.
    Also purges vector store entries and RAG corpus documents tagged to this org.
    """
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    results: dict[str, int] = {}
    # Get member list before deletion
    members = db_list_org_members(org_id)
    member_usernames = [str(m.get("username") or "") for m in members]

    # Delete per-member chats + usage + memory tagged to org
    for uname in member_usernames:
        try:
            n = _sql_execute(f"DELETE FROM chats WHERE username={ph}", (uname,))
            results[f"chats:{uname}"] = n
        except Exception:
            pass
        try:
            n = _sql_execute(f"DELETE FROM usage_log WHERE username={ph}", (uname,))
            results[f"usage_log:{uname}"] = n
        except Exception:
            pass
        try:
            n = _sql_execute(f"DELETE FROM memory WHERE username={ph}", (uname,))
            results[f"memory:{uname}"] = n
        except Exception:
            pass

    # Delete org-level records
    for table, col in [
        ("org_api_keys", "org_id"),
        ("org_members", "org_id"),
        ("org_invites", "org_id"),
        ("orgs", "id"),
    ]:
        try:
            n = _sql_execute(f"DELETE FROM {table} WHERE {col}={ph}", (org_id,))
            results[table] = n
        except Exception:
            pass

    # Purge vector store entries tagged to this org
    try:
        from .memory import _get_collection
        coll = _get_collection()
        if coll:
            existing = coll.get(where={"org_id": {"$eq": org_id}})
            if existing and existing.get("ids"):
                coll.delete(ids=existing["ids"])
                results["chroma_memory"] = len(existing["ids"])
    except Exception:
        pass

    # Purge RAG corpus documents tagged to this org
    try:
        from .rag.rag_system import get_rag_system
        rag = get_rag_system()
        vs = getattr(rag, "vector_store", None)
        if vs is not None:
            all_docs = vs.get_all_documents()
            org_doc_ids = [
                d["id"] for d in all_docs
                if str(d.get("metadata", {}).get("org_id", "")) == org_id
            ]
            if org_doc_ids:
                vs.delete(org_doc_ids)
                results["rag_corpus"] = len(org_doc_ids)
    except Exception:
        pass

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Backup log
# ─────────────────────────────────────────────────────────────────────────────

def record_backup(
    backup_type: str = "local",
    status: str = "ok",
    size_bytes: int = 0,
    location: str = "",
    checksum: str = "",
    error: str = "",
) -> None:
    import time as _t
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO backup_log(ts,type,status,size_bytes,location,checksum,error)"
            " VALUES(?,?,?,?,?,?,?)",
            (_t.time(), backup_type, status, size_bytes, location, checksum, error),
        )
    else:
        _sql_execute(
            "INSERT INTO backup_log(ts,type,status,size_bytes,location,checksum,error)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (_t.time(), backup_type, status, size_bytes, location, checksum, error),
        )


def list_backup_log(limit: int = 50) -> list[dict]:
    return [dict(r) for r in _sql_fetchall(
        f"SELECT * FROM backup_log ORDER BY ts DESC LIMIT {int(limit)}"
    )]


# ─────────────────────────────────────────────────────────────────────────────
# Org-scoped API keys
# ─────────────────────────────────────────────────────────────────────────────

def create_org_api_key(
    key_id: str,
    org_id: str,
    created_by: str,
    key_hash: str,
    key_prefix: str,
    name: str,
    scopes: list,
    created_at: float,
) -> bool:
    scopes_json = json.dumps(scopes)
    if isinstance(_backend, SQLiteBackend):
        changed = _sql_execute(
            "INSERT INTO org_api_keys(id,org_id,created_by,key_hash,key_prefix,name,scopes,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (key_id, org_id, created_by, key_hash, key_prefix, name, scopes_json, created_at),
        )
    else:
        changed = _sql_execute(
            "INSERT INTO org_api_keys(id,org_id,created_by,key_hash,key_prefix,name,scopes,created_at)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (key_id, org_id, created_by, key_hash, key_prefix, name, scopes_json, created_at),
        )
    return changed > 0


def list_org_api_keys(org_id: str) -> list[dict]:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(
        f"SELECT * FROM org_api_keys WHERE org_id={ph} AND revoked_at IS NULL ORDER BY created_at DESC",
        (org_id,),
    )
    result = []
    for r in rows:
        d = dict(r)
        d["scopes"] = json.loads(d.get("scopes") or "[]")
        d.pop("key_hash", None)  # never expose hash
        result.append(d)
    return result


def get_org_api_key_by_hash(key_hash: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(
        f"SELECT * FROM org_api_keys WHERE key_hash={ph} AND revoked_at IS NULL",
        (key_hash,),
    )
    if not rows:
        return None
    d = dict(rows[0])
    d["scopes"] = json.loads(d.get("scopes") or "[]")
    return d


def revoke_org_api_key(key_id: str, org_id: str) -> bool:
    import time as _t
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    n = _sql_execute(
        f"UPDATE org_api_keys SET revoked_at={ph} WHERE id={ph} AND org_id={ph}",
        (_t.time(), key_id, org_id),
    )
    return n > 0


def touch_org_api_key(key_id: str, ts: float) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(
        f"UPDATE org_api_keys SET last_used_at={ph} WHERE id={ph}",
        (ts, key_id),
    )


# ─────────────────────────────────────────────────────────────────────────────
# WebAuthn credential storage
# ─────────────────────────────────────────────────────────────────────────────

def save_webauthn_credential(
    credential_id: str,
    username: str,
    public_key: str,
    sign_count: int,
    device_name: str = "",
) -> str:
    import uuid as _uuid, time as _t
    rec_id = "wau-" + _uuid.uuid4().hex[:12]
    now = _t.time()
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO webauthn_credentials(id,username,credential_id,public_key,sign_count,device_name,created_at)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(credential_id) DO UPDATE SET sign_count=excluded.sign_count, last_used_at=excluded.created_at",
            (rec_id, username, credential_id, public_key, sign_count, device_name, now),
        )
    else:
        _sql_execute(
            "INSERT INTO webauthn_credentials(id,username,credential_id,public_key,sign_count,device_name,created_at)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT(credential_id) DO UPDATE SET sign_count=EXCLUDED.sign_count, last_used_at=EXCLUDED.created_at",
            (rec_id, username, credential_id, public_key, sign_count, device_name, now),
        )
    return rec_id


def get_webauthn_credential(credential_id: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(
        f"SELECT * FROM webauthn_credentials WHERE credential_id={ph}",
        (credential_id,),
    )
    return dict(rows[0]) if rows else None


def list_webauthn_credentials(username: str) -> list[dict]:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    return [dict(r) for r in _sql_fetchall(
        f"SELECT * FROM webauthn_credentials WHERE username={ph} ORDER BY created_at DESC",
        (username,),
    )]


def update_webauthn_sign_count(credential_id: str, sign_count: int) -> None:
    import time as _t
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(
        f"UPDATE webauthn_credentials SET sign_count={ph}, last_used_at={ph} WHERE credential_id={ph}",
        (sign_count, _t.time(), credential_id),
    )


def delete_webauthn_credential(credential_id: str, username: str) -> bool:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    n = _sql_execute(
        f"DELETE FROM webauthn_credentials WHERE credential_id={ph} AND username={ph}",
        (credential_id, username),
    )
    return n > 0


# ─────────────────────────────────────────────────────────────────────────────
# SAML session storage
# ─────────────────────────────────────────────────────────────────────────────

def save_saml_session(session_id: str, provider: str, relay_state: str, expires_at: float) -> None:
    import time as _t
    if isinstance(_backend, SQLiteBackend):
        _sql_execute(
            "INSERT INTO saml_sessions(id,username,provider,relay_state,nameid,created_at,expires_at)"
            " VALUES(?,'',%s,?,?,?,?) ",
            (session_id, provider, relay_state, "", _t.time(), expires_at),
        )
    else:
        _sql_execute(
            "INSERT INTO saml_sessions(id,username,provider,relay_state,nameid,created_at,expires_at)"
            " VALUES(%s,'',%s,%s,'',%s,%s)",
            (session_id, provider, relay_state, _t.time(), expires_at),
        )


def save_saml_session_v2(session_id: str, provider: str, relay_state: str, expires_at: float) -> None:
    import time as _t
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(
        f"INSERT INTO saml_sessions(id,username,provider,relay_state,nameid,created_at,expires_at)"
        f" VALUES({ph},'',%s,{ph},'',%s,{ph})".replace("%s", ph),
        (session_id, provider, relay_state, _t.time(), expires_at),
    )


def complete_saml_session(session_id: str, username: str, nameid: str) -> None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    _sql_execute(
        f"UPDATE saml_sessions SET username={ph}, nameid={ph} WHERE id={ph}",
        (username, nameid, session_id),
    )


def get_saml_session(session_id: str) -> dict | None:
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    rows = _sql_fetchall(f"SELECT * FROM saml_sessions WHERE id={ph}", (session_id,))
    return dict(rows[0]) if rows else None


# ─────────────────────────────────────────────────────────────────────────────
# Async PostgreSQL pool (asyncpg) — optional, used by async-path routes
# ─────────────────────────────────────────────────────────────────────────────

class AsyncPgPool:
    """
    Async-safe PostgreSQL connection pool backed by asyncpg.
    Instantiated once in app lifespan via init_async_pool().
    Routes that need async DB access call async_pg_query() / async_pg_execute().
    Existing synchronous psycopg2 routes are unaffected.
    """

    def __init__(self) -> None:
        self._pool = None

    async def init(self, dsn: str, min_size: int = 2, max_size: int = 10) -> None:
        try:
            import asyncpg  # type: ignore
            self._pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=min_size,
                max_size=max_size,
                command_timeout=30,
            )
        except ImportError:
            pass  # asyncpg not installed — fall back to sync pool
        except Exception:
            pass  # connection failed — fall back gracefully

    async def query(self, sql: str, *args) -> list[dict]:
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *args)
                return [dict(r) for r in rows]
        except Exception:
            return []

    async def execute(self, sql: str, *args) -> int:
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(sql, *args)
                # asyncpg returns "UPDATE N" / "INSERT N" / etc.
                parts = result.split()
                return int(parts[-1]) if parts and parts[-1].isdigit() else 0
        except Exception:
            return 0

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def available(self) -> bool:
        return self._pool is not None


_async_pg_pool = AsyncPgPool()


async def init_async_pool() -> None:
    """Initialize the asyncpg pool from the same DATABASE_URL used by the sync backend.
    Called from app lifespan if DATABASE_URL points at PostgreSQL."""
    if not (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")):
        return
    pgbouncer_dsn = os.getenv("PGBOUNCER_DSN", "").strip()
    dsn = pgbouncer_dsn if pgbouncer_dsn else DATABASE_URL
    min_size = int(os.getenv("PG_ASYNC_POOL_MIN", "2"))
    max_size = int(os.getenv("PG_ASYNC_POOL_SIZE", "10"))
    await _async_pg_pool.init(dsn, min_size=min_size, max_size=max_size)


async def close_async_pool() -> None:
    await _async_pg_pool.close()


async def async_pg_query(sql: str, *args) -> list[dict]:
    """Async SQL query helper — uses asyncpg pool when available."""
    return await _async_pg_pool.query(sql, *args)


async def async_pg_execute(sql: str, *args) -> int:
    """Async SQL execute helper — uses asyncpg pool when available."""
    return await _async_pg_pool.execute(sql, *args)


# ─────────────────────────────────────────────────────────────────────────────
# Per-org data isolation helpers
# These functions provide org-scoped views over shared tables, enabling
# multi-tenant query isolation without schema changes.
# ─────────────────────────────────────────────────────────────────────────────


def _get_org_member_usernames(org_id: str) -> list[str]:
    """Return the list of usernames that belong to org_id."""
    members = db_list_org_members(org_id)
    return [str(m.get("username") or "") for m in members if m.get("username")]


def get_org_chats(org_id: str, limit: int = 500) -> list[dict]:
    """Return all chats belonging to members of org_id."""
    usernames = _get_org_member_usernames(org_id)
    if not usernames:
        return []
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    placeholders = ",".join([ph] * len(usernames))
    rows = _sql_fetchall(
        f"SELECT * FROM chats WHERE username IN ({placeholders}) ORDER BY updated_at DESC LIMIT {int(limit)}",
        tuple(usernames),
    )
    return [dict(r) for r in rows]


def get_org_usage(org_id: str, days: int = 30) -> list[dict]:
    """Return usage log rows for all members of org_id within the last N days."""
    usernames = _get_org_member_usernames(org_id)
    if not usernames:
        return []
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    placeholders = ",".join([ph] * len(usernames))
    import time as _t
    since = _t.time() - days * 86400
    rows = _sql_fetchall(
        f"SELECT * FROM usage_log WHERE username IN ({placeholders}) AND ts >= {ph} ORDER BY ts DESC LIMIT 5000",
        tuple(usernames) + (since,),
    )
    return [dict(r) for r in rows]


def get_org_memory_entries(org_id: str, limit: int = 200) -> list[dict]:
    """Return memory entries tagged to org_id (if the memory table has an org_id column)."""
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    try:
        rows = _sql_fetchall(
            f"SELECT * FROM memory WHERE org_id={ph} ORDER BY created_at DESC LIMIT {int(limit)}",
            (org_id,),
        )
        return [dict(r) for r in rows]
    except Exception:
        # If the memory table doesn't have an org_id column yet, fall back to member query
        usernames = _get_org_member_usernames(org_id)
        if not usernames:
            return []
        placeholders = ",".join([ph] * len(usernames))
        try:
            rows = _sql_fetchall(
                f"SELECT * FROM memory WHERE username IN ({placeholders}) ORDER BY created_at DESC LIMIT {int(limit)}",
                tuple(usernames),
            )
            return [dict(r) for r in rows]
        except Exception:
            return []


def tag_memory_with_org(entry_id: str, org_id: str) -> bool:
    """Tag a memory entry with an org_id (best-effort; silently skips if column absent)."""
    ph = "?" if isinstance(_backend, SQLiteBackend) else "%s"
    try:
        _sql_execute(
            f"ALTER TABLE memory ADD COLUMN org_id TEXT NOT NULL DEFAULT ''"
        )
    except Exception:
        pass  # column already exists or not supported
    try:
        _sql_execute(
            f"UPDATE memory SET org_id={ph} WHERE id={ph}",
            (org_id, entry_id),
        )
        return True
    except Exception:
        return False


def get_org_rag_documents(org_id: str) -> list[dict]:
    """
    Return all RAG corpus documents tagged with org_id.
    Uses the vector store's metadata filter — no DB scan required.
    Returns [] gracefully if RAG is not configured.
    """
    try:
        from .rag.rag_system import get_rag_system
        rag = get_rag_system()
        vs = getattr(rag, "vector_store", None)
        if vs is None:
            return []
        all_docs = vs.get_all_documents()
        return [d for d in all_docs if str(d.get("metadata", {}).get("org_id", "")) == org_id]
    except Exception:
        return []


def ingest_rag_for_org(text: str, org_id: str, source: str = "", metadata: dict | None = None) -> bool:
    """
    Ingest a text document into the RAG corpus tagged with org_id.
    Wraps the RAG pipeline's ingest call and ensures org_id is always present in metadata.
    """
    try:
        from .rag.rag_system import get_rag_system
        rag = get_rag_system()
        combined_meta = dict(metadata or {})
        combined_meta["org_id"] = org_id
        if source:
            combined_meta["source"] = source
        rag.ingest(text, metadata=combined_meta)
        return True
    except Exception:
        return False


# ── Marketplace agents ────────────────────────────────────────────────────────

def _mkt_index_key() -> str:
    return "mkt_agents:index"


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
    org_id: str = "",
    version: int = 1,
) -> None:
    """Persist a marketplace agent.  Overwrites existing record with same id."""
    record = {
        "id":                  agent_id,
        "name":                name,
        "icon":                icon,
        "description":         description,
        "system_prompt":       system_prompt,
        "keywords":            keywords,
        "preferred_providers": preferred_providers,
        "temperature":         temperature,
        "tier":                tier,
        "source":              source,
        "org_id":              org_id,
        "version":             version,
        "created_at":          time.time(),
    }
    save_pref(f"mkt_agent:{agent_id}", json.dumps(record))
    # update index
    raw = load_pref(_mkt_index_key(), "[]")
    try:
        index: list = json.loads(raw)
    except Exception:
        index = []
    if agent_id not in index:
        index.append(agent_id)
    save_pref(_mkt_index_key(), json.dumps(index))


def load_marketplace_agents(source: str | None = None, org_id: str | None = None) -> list[dict]:
    """Return all marketplace agents, optionally filtered by source or org_id."""
    raw = load_pref(_mkt_index_key(), "[]")
    try:
        index: list = json.loads(raw)
    except Exception:
        return []
    agents = []
    for aid in index:
        raw_agent = load_pref(f"mkt_agent:{aid}", "")
        if not raw_agent:
            continue
        try:
            rec = json.loads(raw_agent)
        except Exception:
            continue
        if source is not None and rec.get("source") != source:
            continue
        if org_id is not None and rec.get("org_id") != org_id:
            continue
        agents.append(rec)
    return agents


def delete_marketplace_agent(agent_id: str) -> bool:
    """Remove a marketplace agent by id. Returns True if it existed."""
    raw = load_pref(f"mkt_agent:{agent_id}", "")
    if not raw:
        return False
    save_pref(f"mkt_agent:{agent_id}", "")
    # remove from index
    raw_idx = load_pref(_mkt_index_key(), "[]")
    try:
        index: list = json.loads(raw_idx)
    except Exception:
        index = []
    index = [i for i in index if i != agent_id]
    save_pref(_mkt_index_key(), json.dumps(index))
    return True


def save_marketplace_agent_review(
    agent_id: str,
    username: str,
    rating: int,
    comment: str,
) -> dict:
    """Save a review for a marketplace agent (one review per username/agent pair)."""
    review_key = f"mkt_reviews:{agent_id}"
    raw = load_pref(review_key, "{}")
    try:
        reviews: dict = json.loads(raw)
    except Exception:
        reviews = {}
    reviews[username] = {
        "username": username,
        "rating":   max(1, min(5, int(rating))),
        "comment":  str(comment)[:1000],
        "ts":       time.time(),
    }
    save_pref(review_key, json.dumps(reviews))
    return reviews[username]


def list_marketplace_agent_reviews(agent_id: str) -> list[dict]:
    """Return all reviews for a marketplace agent, sorted newest first."""
    raw = load_pref(f"mkt_reviews:{agent_id}", "{}")
    try:
        reviews: dict = json.loads(raw)
    except Exception:
        return []
    return sorted(reviews.values(), key=lambda r: r.get("ts", 0), reverse=True)


def list_marketplace_agent_versions(agent_id: str) -> list[dict]:
    """Return version history for a marketplace agent (simplified — current + archived)."""
    raw_versions = load_pref(f"mkt_agent_versions:{agent_id}", "[]")
    try:
        versions: list = json.loads(raw_versions)
    except Exception:
        versions = []
    # Include current record as the latest version entry
    raw_current = load_pref(f"mkt_agent:{agent_id}", "")
    if raw_current:
        try:
            current = json.loads(raw_current)
            entry = {
                "version":    current.get("version", 1),
                "name":       current.get("name", ""),
                "saved_at":   current.get("created_at", 0),
                "is_current": True,
            }
            # de-duplicate
            versions = [v for v in versions if v.get("version") != entry["version"]]
            versions.append(entry)
            versions.sort(key=lambda v: v.get("version", 0), reverse=True)
        except Exception:
            pass
    return versions


# ── Architecture blueprints ───────────────────────────────────────────────────

def _bp_index_key() -> str:
    return "arch_blueprints:index"


def save_architecture_blueprint(name: str, snapshot: dict, notes: str = "") -> dict:
    """Save a named blueprint snapshot. Each save increments the version counter."""
    # load current version counter
    raw_current = load_pref(f"arch_bp:{name}:latest", "")
    current_version = 0
    if raw_current:
        try:
            current_version = json.loads(raw_current).get("version", 0)
        except Exception:
            pass
    new_version = current_version + 1
    record = {
        "name":       name,
        "version":    new_version,
        "snapshot":   snapshot,
        "notes":      notes,
        "saved_at":   time.time(),
    }
    save_pref(f"arch_bp:{name}:v{new_version}", json.dumps(record))
    save_pref(f"arch_bp:{name}:latest",          json.dumps(record))
    # update index
    raw_idx = load_pref(_bp_index_key(), "[]")
    try:
        index: list = json.loads(raw_idx)
    except Exception:
        index = []
    if name not in index:
        index.append(name)
    save_pref(_bp_index_key(), json.dumps(index))
    return record


def load_architecture_blueprint(name: str, version: int | None = None) -> dict | None:
    """Load a named blueprint (latest, or a specific version)."""
    if version is not None:
        raw = load_pref(f"arch_bp:{name}:v{version}", "")
    else:
        raw = load_pref(f"arch_bp:{name}:latest", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def list_architecture_blueprints(name: str = "", limit: int = 50) -> list[dict]:
    """List saved blueprints, including historical versions for each name."""
    raw_idx = load_pref(_bp_index_key(), "[]")
    try:
        index: list = json.loads(raw_idx)
    except Exception:
        return []
    results = []
    for bp_name in index:
        if name and not bp_name.startswith(name):
            continue
        latest_raw = load_pref(f"arch_bp:{bp_name}:latest", "")
        if not latest_raw:
            continue
        try:
            latest_rec = json.loads(latest_raw)
            latest_version = int(latest_rec.get("version", 0) or 0)
        except Exception:
            latest_version = 0
        if latest_version <= 0:
            continue

        for ver in range(1, latest_version + 1):
            raw = load_pref(f"arch_bp:{bp_name}:v{ver}", "")
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                results.append({
                    "name": rec["name"],
                    "version": rec["version"],
                    "notes": rec.get("notes", ""),
                    "saved_at": rec.get("saved_at", 0),
                })
            except Exception:
                continue

    results.sort(key=lambda r: r.get("saved_at", 0), reverse=True)
    return results[:limit]


def load_architecture_registry(name: str, version: int | None = None) -> dict | None:
    """Load a registry entry (alias for load_architecture_blueprint for now)."""
    return load_architecture_blueprint(name, version)





# ── Team budget / spending — DB-persisted functions ──────────────────────────
# Uses _load_json_pref/_save_json_pref so data survives container restarts.
# Keys are namespaced to avoid collisions with other prefs.

def db_set_team_budget(team_id: str, monthly_limit_usd: float,
                       daily_limit_usd: float = 0.0,
                       alert_threshold_pct: float = 80.0) -> None:
    from datetime import datetime, timezone
    budgets = _load_json_pref("slo:team_budgets", {})
    budgets[team_id] = {
        "team_id": team_id,
        "monthly_limit_usd": float(monthly_limit_usd),
        "daily_limit_usd": float(daily_limit_usd),
        "alert_threshold_pct": float(alert_threshold_pct),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_json_pref("slo:team_budgets", budgets)
    # Ensure spending row exists
    spending = _load_json_pref("slo:team_spending", {})
    if team_id not in spending:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month  = datetime.now(timezone.utc).strftime("%Y-%m")
        spending[team_id] = {"team_id": team_id, "today_usd": 0.0, "month_usd": 0.0,
                             "total_usd": 0.0, "reset_date": today, "reset_month": month}
        _save_json_pref("slo:team_spending", spending)


def db_get_team_budget(team_id: str) -> dict | None:
    budgets = _load_json_pref("slo:team_budgets", {})
    return budgets.get(team_id)


def db_list_team_budgets() -> list[dict]:
    return list(_load_json_pref("slo:team_budgets", {}).values())


def db_get_team_spending(team_id: str) -> dict:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    spending = _load_json_pref("slo:team_spending", {})
    row = spending.get(team_id, {"team_id": team_id, "today_usd": 0.0, "month_usd": 0.0,
                                 "total_usd": 0.0, "reset_date": today, "reset_month": month})
    changed = False
    if row.get("reset_date") != today:
        row["today_usd"] = 0.0
        row["reset_date"] = today
        changed = True
    if row.get("reset_month") != month:
        row["month_usd"] = 0.0
        row["reset_month"] = month
        changed = True
    if changed:
        spending[team_id] = row
        _save_json_pref("slo:team_spending", spending)
    return dict(row)


def db_add_team_spending(team_id: str, cost_usd: float) -> dict:
    row = db_get_team_spending(team_id)   # handles auto-reset
    row["today_usd"] = round(row.get("today_usd", 0.0) + cost_usd, 6)
    row["month_usd"] = round(row.get("month_usd", 0.0) + cost_usd, 6)
    row["total_usd"] = round(row.get("total_usd", 0.0) + cost_usd, 6)
    spending = _load_json_pref("slo:team_spending", {})
    spending[team_id] = row
    _save_json_pref("slo:team_spending", spending)
    return dict(row)


def db_add_budget_alert(team_id: str, alert_type: str,
                        utilization: float, threshold: float) -> dict:
    import uuid as _uuid
    from datetime import datetime, timezone
    aid = str(_uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    alerts = _load_json_pref("slo:budget_alerts", [])
    entry = {"id": aid, "team_id": team_id, "alert_type": alert_type,
             "utilization": round(utilization, 4), "threshold": round(threshold, 4), "ts": now}
    alerts.append(entry)
    _save_json_pref("slo:budget_alerts", alerts[-5000:])
    return entry


def db_list_budget_alerts(team_id: str | None = None, limit: int = 100) -> list[dict]:
    alerts = _load_json_pref("slo:budget_alerts", [])
    if team_id:
        alerts = [a for a in alerts if a.get("team_id") == team_id]
    return list(reversed(alerts))[:max(1, min(int(limit), 5000))]


# ── Attribution log — DB-persisted ───────────────────────────────────────────

def db_record_attribution(team_id: str, department: str, username: str,
                           cost_usd: float, tokens: int,
                           model: str = "", endpoint: str = "") -> dict:
    import uuid as _uuid
    from datetime import datetime, timezone
    aid = str(_uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    entry = {"id": aid, "ts": now, "team_id": team_id, "department": department,
             "user": username, "cost_usd": cost_usd, "tokens": tokens,
             "model": model, "endpoint": endpoint}
    log = _load_json_pref("slo:attribution_log", [])
    log.append(entry)
    _save_json_pref("slo:attribution_log", log[-10000:])
    return entry


def db_get_attribution_report(team_id: str | None = None,
                               department: str | None = None,
                               limit: int = 500) -> list[dict]:
    items = _load_json_pref("slo:attribution_log", [])
    if team_id:
        items = [r for r in items if r.get("team_id") == team_id]
    if department:
        items = [r for r in items if r.get("department") == department]
    return list(reversed(items))[:max(1, min(int(limit), 5000))]


# ── Department quota / usage — DB-persisted ───────────────────────────────────

def db_set_department_quota(department: str, daily_tokens: int = 0,
                             monthly_cost_cap: float = 0.0) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    quotas = _load_json_pref("tp:department_quotas", {})
    quotas[department] = {"department": department, "daily_tokens": int(daily_tokens),
                           "monthly_cost_cap": float(monthly_cost_cap), "updated_at": now}
    _save_json_pref("tp:department_quotas", quotas)
    # ensure usage row exists
    usage = _load_json_pref("tp:department_usage", {})
    if department not in usage:
        usage[department] = {"department": department, "tokens_today": 0,
                              "cost_this_month": 0.0, "users": 0}
        _save_json_pref("tp:department_usage", usage)
    return dict(quotas[department])


def db_get_department_quota(department: str) -> dict | None:
    from datetime import datetime, timezone
    quota = _load_json_pref("tp:department_quotas", {}).get(department)
    if not quota:
        return None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month  = datetime.now(timezone.utc).strftime("%Y-%m")
    usage_all = _load_json_pref("tp:department_usage", {})
    row = usage_all.get(department, {"tokens_today": 0, "cost_this_month": 0.0})
    changed = False
    if row.get("reset_date") != today:
        row["tokens_today"] = 0
        row["reset_date"] = today
        changed = True
    if row.get("reset_month") != month:
        row["cost_this_month"] = 0.0
        row["reset_month"] = month
        changed = True
    if changed:
        usage_all[department] = row
        _save_json_pref("tp:department_usage", usage_all)
    return {**quota, "usage": dict(row)}


def db_list_department_quotas() -> list[dict]:
    quotas = _load_json_pref("tp:department_quotas", {})
    return [db_get_department_quota(d) for d in quotas if d]


def db_add_department_usage(department: str, tokens: int, cost_usd: float = 0.0) -> dict:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month  = datetime.now(timezone.utc).strftime("%Y-%m")
    db_get_department_quota(department)   # trigger auto-reset if needed
    usage_all = _load_json_pref("tp:department_usage", {})
    row = usage_all.get(department, {"department": department, "tokens_today": 0,
                                      "cost_this_month": 0.0, "users": 0,
                                      "reset_date": today, "reset_month": month})
    row["tokens_today"] = int(row.get("tokens_today", 0)) + int(tokens)
    row["cost_this_month"] = round(float(row.get("cost_this_month", 0.0)) + float(cost_usd), 6)
    usage_all[department] = row
    _save_json_pref("tp:department_usage", usage_all)
    return db_get_department_quota(department) or {}


# ── Safety audit log — DB-persisted via existing add_safety_audit_entry ───────
# Thin wrappers that call the existing hash-chained audit log.

def db_log_safety_event(event_type: str, session_id: str, username: str,
                         severity: str, details: dict) -> None:
    from datetime import datetime, timezone
    add_safety_audit_entry({
        "event_type":  event_type,
        "session_id":  session_id,
        "username":    username,
        "severity":    severity,
        "details":     details,
        "created_at":  datetime.now(timezone.utc).isoformat(),
    })


def db_query_safety_events(event_type: str | None = None,
                            username: str | None = None,
                            since: str | None = None,
                            limit: int = 100) -> list[dict]:
    events = _load_json_pref("safety_audit_log", [])
    if not isinstance(events, list):
        return []
    filtered = []
    for ev in events:
        if event_type and ev.get("event_type") != event_type:
            continue
        if username and ev.get("username") != username:
            continue
        if since and (ev.get("created_at") or ev.get("ts") or "") < since:
            continue
        filtered.append(ev)
    return list(reversed(filtered))[:max(1, min(int(limit), 5000))]
