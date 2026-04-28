"""
Nexus AI — Online DDL helpers for zero-downtime schema migrations.

Provides non-blocking schema evolution:
  - add_column_if_missing()  — ALTER TABLE ADD COLUMN IF NOT EXISTS (SQLite + PG)
  - create_index_if_missing() — CREATE INDEX CONCURRENTLY (PG) / CREATE INDEX IF NOT EXISTS (SQLite)
  - run_pending_migrations()  — apply all registered migrations; called from app lifespan

All operations are idempotent. Errors are logged but never crash startup.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger("nexus.online_ddl")

# ── Migration registry ─────────────────────────────────────────────────────


_PENDING_MIGRATIONS: list[dict] = [
    # Format: {"id": str, "description": str, "fn": Callable}
]


def register_migration(migration_id: str, description: str, fn: Callable) -> None:
    """Register a migration function. Called at module load time."""
    _PENDING_MIGRATIONS.append(
        {"id": migration_id, "description": description, "fn": fn}
    )


# ── Low-level DDL helpers ──────────────────────────────────────────────────


def add_column_if_missing(
    table: str,
    column: str,
    column_def: str,
    backend=None,
) -> bool:
    """
    Add a column to a table if it doesn't exist yet.
    Returns True on success / already-exists, False on error.

    For PostgreSQL the command is:
        ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_def}
    For SQLite the command is:
        ALTER TABLE {table} ADD COLUMN {column} {column_def}
    (SQLite doesn't support IF NOT EXISTS on ADD COLUMN but errors silently.)
    """
    from .db import _backend, SQLiteBackend, PostgresBackend, _sql_execute

    b = backend or _backend
    try:
        if isinstance(b, SQLiteBackend):
            _sql_execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
        else:
            _sql_execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_def}"
            )
        logger.info("online_ddl.add_column table=%s column=%s status=added", table, column)
        return True
    except Exception as exc:
        err = str(exc).lower()
        if "duplicate column" in err or "already exists" in err:
            return True
        logger.warning(
            "online_ddl.add_column_failed table=%s column=%s error=%s", table, column, exc
        )
        return False


def create_index_if_missing(
    index_name: str,
    table: str,
    columns: str,
    *,
    unique: bool = False,
    backend=None,
) -> bool:
    """
    Create an index if it doesn't already exist.
    PostgreSQL uses CREATE INDEX CONCURRENTLY (no table lock).
    SQLite uses CREATE INDEX IF NOT EXISTS (always non-blocking).
    Returns True on success / already-exists, False on error.
    """
    from .db import _backend, SQLiteBackend, _sql_execute

    b = backend or _backend
    unique_kw = "UNIQUE " if unique else ""
    try:
        if isinstance(b, SQLiteBackend):
            _sql_execute(
                f"CREATE {unique_kw}INDEX IF NOT EXISTS {index_name} ON {table}({columns})"
            )
        else:
            # PostgreSQL CONCURRENTLY cannot run inside a transaction block;
            # _sql_execute uses connection-level commit so this is safe.
            _sql_execute(
                f"CREATE {unique_kw}INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table}({columns})"
            )
        logger.info("online_ddl.create_index index=%s table=%s status=ok", index_name, table)
        return True
    except Exception as exc:
        err = str(exc).lower()
        if "already exists" in err:
            return True
        logger.warning(
            "online_ddl.create_index_failed index=%s table=%s error=%s", index_name, table, exc
        )
        return False


def drop_column_if_exists(table: str, column: str, backend=None) -> bool:
    """
    Drop a column from a table if it exists. PostgreSQL only
    (SQLite does not support DROP COLUMN before 3.35.0, silently skipped there).
    """
    from .db import _backend, SQLiteBackend, _sql_execute

    b = backend or _backend
    if isinstance(b, SQLiteBackend):
        logger.debug(
            "online_ddl.drop_column skipped (SQLite) table=%s column=%s", table, column
        )
        return True
    try:
        _sql_execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
        return True
    except Exception as exc:
        logger.warning(
            "online_ddl.drop_column_failed table=%s column=%s error=%s", table, column, exc
        )
        return False


# ── Built-in migrations ───────────────────────────────────────────────────


def _migration_chats_username(backend=None) -> None:
    """Add username column to chats for GDPR cascade and per-user queries."""
    add_column_if_missing("chats", "username", "TEXT NOT NULL DEFAULT ''", backend=backend)
    create_index_if_missing(
        "idx_chats_username", "chats", "username", backend=backend
    )


def _migration_org_api_keys_table(backend=None) -> None:
    """Ensure org_api_keys table exists (also created in SQLiteBackend.init_db)."""
    from .db import _backend, SQLiteBackend, _sql_execute
    b = backend or _backend
    if isinstance(b, SQLiteBackend):
        return  # SQLiteBackend.init_db already creates the table
    # PostgreSQL: ensure table exists
    try:
        _sql_execute("""
            CREATE TABLE IF NOT EXISTS org_api_keys (
                id           TEXT PRIMARY KEY,
                org_id       TEXT NOT NULL,
                created_by   TEXT NOT NULL,
                key_hash     TEXT NOT NULL UNIQUE,
                key_prefix   TEXT NOT NULL,
                name         TEXT NOT NULL,
                scopes       TEXT NOT NULL DEFAULT '[]',
                created_at   DOUBLE PRECISION NOT NULL,
                last_used_at DOUBLE PRECISION,
                revoked_at   DOUBLE PRECISION
            )
        """)
    except Exception as exc:
        logger.warning("online_ddl._migration_org_api_keys error=%s", exc)


def _migration_webauthn_table(backend=None) -> None:
    """Ensure webauthn_credentials table exists."""
    from .db import _backend, SQLiteBackend, _sql_execute
    b = backend or _backend
    if isinstance(b, SQLiteBackend):
        return
    try:
        _sql_execute("""
            CREATE TABLE IF NOT EXISTS webauthn_credentials (
                id              TEXT PRIMARY KEY,
                username        TEXT NOT NULL,
                credential_id   TEXT NOT NULL UNIQUE,
                public_key      TEXT NOT NULL,
                sign_count      INTEGER NOT NULL DEFAULT 0,
                device_name     TEXT NOT NULL DEFAULT '',
                created_at      DOUBLE PRECISION NOT NULL,
                last_used_at    DOUBLE PRECISION
            )
        """)
    except Exception as exc:
        logger.warning("online_ddl._migration_webauthn error=%s", exc)


def _migration_saml_sessions_table(backend=None) -> None:
    """Ensure saml_sessions table exists."""
    from .db import _backend, SQLiteBackend, _sql_execute
    b = backend or _backend
    if isinstance(b, SQLiteBackend):
        return
    try:
        _sql_execute("""
            CREATE TABLE IF NOT EXISTS saml_sessions (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL DEFAULT '',
                provider    TEXT NOT NULL DEFAULT '',
                relay_state TEXT NOT NULL DEFAULT '',
                nameid      TEXT NOT NULL DEFAULT '',
                created_at  DOUBLE PRECISION NOT NULL,
                expires_at  DOUBLE PRECISION NOT NULL
            )
        """)
    except Exception as exc:
        logger.warning("online_ddl._migration_saml_sessions error=%s", exc)


# Register built-in migrations
register_migration(
    "0002_chats_username",
    "Add username column to chats for GDPR cascade",
    _migration_chats_username,
)
register_migration(
    "0003_org_api_keys",
    "Ensure org_api_keys table exists in PostgreSQL",
    _migration_org_api_keys_table,
)
register_migration(
    "0004_webauthn",
    "Ensure webauthn_credentials table exists in PostgreSQL",
    _migration_webauthn_table,
)
register_migration(
    "0005_saml_sessions",
    "Ensure saml_sessions table exists in PostgreSQL",
    _migration_saml_sessions_table,
)


# ── Runner ────────────────────────────────────────────────────────────────


def run_pending_migrations(backend=None) -> dict[str, str]:
    """
    Run all registered online DDL migrations.
    Returns a dict of {migration_id: "ok" | "failed" | "skipped"}.
    Safe to call multiple times — all migrations are idempotent.
    """
    results: dict[str, str] = {}
    for m in _PENDING_MIGRATIONS:
        mid = str(m.get("id") or "unknown")
        try:
            fn = m.get("fn")
            if callable(fn):
                fn(backend=backend)
            results[mid] = "ok"
            logger.debug("online_ddl.migration_ok id=%s", mid)
        except Exception as exc:
            results[mid] = f"failed: {exc}"
            logger.warning("online_ddl.migration_failed id=%s error=%s", mid, exc)
    return results
