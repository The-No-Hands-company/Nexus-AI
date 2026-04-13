"""
Knowledge Graph — SQLite-backed long-term entity/relation memory.

Tables:
  kg_entities  (id TEXT PK, name TEXT UNIQUE, type TEXT, facts TEXT, created_at TEXT, updated_at TEXT)
  kg_relations (id INTEGER PK, from_entity TEXT, relation TEXT, to_entity TEXT, weight REAL, created_at TEXT)

Public API:
  init_kg_tables()
  kg_store(name, entity_type, facts, relations) -> str
  kg_query(query, limit) -> list[dict]
  kg_list_entities(entity_type) -> list[dict]
  kg_relate(from_entity, relation, to_entity, weight) -> None
  kg_get(name) -> dict | None
  kg_to_context_string(query) -> str
  kg_delete(name) -> bool
"""

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "/tmp/nexus_ai.db")
_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "kg_conn") or _local.kg_conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.kg_conn = conn
    return _local.kg_conn


def init_kg_tables() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS kg_entities (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            type       TEXT NOT NULL DEFAULT 'concept',
            facts      TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(name)
        );
        CREATE TABLE IF NOT EXISTS kg_relations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            from_entity TEXT NOT NULL,
            relation    TEXT NOT NULL,
            to_entity   TEXT NOT NULL,
            weight      REAL NOT NULL DEFAULT 1.0,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(type);
        CREATE INDEX IF NOT EXISTS idx_kg_relations_from ON kg_relations(from_entity);
        CREATE INDEX IF NOT EXISTS idx_kg_relations_to   ON kg_relations(to_entity);
    """)
    c.commit()


# Initialise on import
init_kg_tables()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def kg_store(
    name: str,
    entity_type: str = "concept",
    facts: dict | None = None,
    relations: list[dict] | None = None,
) -> str:
    """Upsert an entity and optionally add relations.

    ``relations`` items: {"relation": "...", "to": "...entity name...", "weight": 1.0}

    Returns the entity id.
    """
    if not name or not name.strip():
        return ""
    name = name.strip()
    facts = facts or {}
    entity_type = (entity_type or "concept").strip()
    now = _now()
    eid = str(uuid.uuid4())
    c = _conn()
    # Upsert: insert or update facts + updated_at
    existing = c.execute("SELECT id, facts FROM kg_entities WHERE name = ?", (name,)).fetchone()
    if existing:
        eid = existing["id"]
        existing_facts = json.loads(existing["facts"] or "{}")
        existing_facts.update(facts)
        c.execute(
            "UPDATE kg_entities SET type=?, facts=?, updated_at=? WHERE id=?",
            (entity_type, json.dumps(existing_facts), now, eid),
        )
    else:
        c.execute(
            "INSERT INTO kg_entities (id, name, type, facts, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (eid, name, entity_type, json.dumps(facts), now, now),
        )

    if relations:
        for rel in relations:
            to_name = (rel.get("to") or "").strip()
            relation = (rel.get("relation") or "related_to").strip()
            weight = float(rel.get("weight", 1.0))
            if to_name:
                kg_relate(name, relation, to_name, weight)

    c.commit()
    return eid


def kg_relate(
    from_entity: str,
    relation: str,
    to_entity: str,
    weight: float = 1.0,
) -> None:
    """Add a directed relation between two entities (idempotent)."""
    if not from_entity or not to_entity:
        return
    now = _now()
    c = _conn()
    # Avoid exact duplicates
    existing = c.execute(
        "SELECT id FROM kg_relations WHERE from_entity=? AND relation=? AND to_entity=?",
        (from_entity, relation, to_entity),
    ).fetchone()
    if not existing:
        c.execute(
            "INSERT INTO kg_relations (from_entity, relation, to_entity, weight, created_at) VALUES (?,?,?,?,?)",
            (from_entity, relation, to_entity, weight, now),
        )
        c.commit()


def kg_get(name: str) -> dict | None:
    """Return full entity with outgoing and incoming relations, or None."""
    if not name:
        return None
    c = _conn()
    row = c.execute("SELECT * FROM kg_entities WHERE name = ?", (name.strip(),)).fetchone()
    if not row:
        return None
    entity = dict(row)
    entity["facts"] = json.loads(entity.get("facts") or "{}")
    outgoing = c.execute(
        "SELECT relation, to_entity, weight FROM kg_relations WHERE from_entity=?", (name,)
    ).fetchall()
    incoming = c.execute(
        "SELECT relation, from_entity, weight FROM kg_relations WHERE to_entity=?", (name,)
    ).fetchall()
    entity["relations"] = [
        {"direction": "out", "relation": r["relation"], "entity": r["to_entity"], "weight": r["weight"]}
        for r in outgoing
    ] + [
        {"direction": "in", "relation": r["relation"], "entity": r["from_entity"], "weight": r["weight"]}
        for r in incoming
    ]
    return entity


def kg_query(query: str, limit: int = 10) -> list[dict]:
    """Fuzzy search over entity names and facts text. Returns matched entities with relations."""
    if not query:
        return []
    q = f"%{query.strip()}%"
    c = _conn()
    rows = c.execute(
        "SELECT * FROM kg_entities WHERE name LIKE ? OR facts LIKE ? ORDER BY updated_at DESC LIMIT ?",
        (q, q, limit),
    ).fetchall()
    results = []
    for row in rows:
        entity = dict(row)
        entity["facts"] = json.loads(entity.get("facts") or "{}")
        outgoing = c.execute(
            "SELECT relation, to_entity, weight FROM kg_relations WHERE from_entity=?",
            (entity["name"],),
        ).fetchall()
        entity["relations"] = [
            {"relation": r["relation"], "entity": r["to_entity"], "weight": r["weight"]}
            for r in outgoing
        ]
        results.append(entity)
    return results


def kg_list_entities(entity_type: str | None = None, limit: int = 100) -> list[dict]:
    """List entities, optionally filtered by type."""
    c = _conn()
    if entity_type:
        rows = c.execute(
            "SELECT id, name, type, updated_at FROM kg_entities WHERE type=? ORDER BY updated_at DESC LIMIT ?",
            (entity_type, limit),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT id, name, type, updated_at FROM kg_entities ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def kg_delete(name: str) -> bool:
    """Delete an entity and all its relations."""
    if not name:
        return False
    c = _conn()
    result = c.execute("DELETE FROM kg_entities WHERE name=?", (name.strip(),))
    if result.rowcount > 0:
        c.execute(
            "DELETE FROM kg_relations WHERE from_entity=? OR to_entity=?", (name, name)
        )
        c.commit()
        return True
    return False


def kg_to_context_string(query: str, limit: int = 5) -> str:
    """Format the top KG matches as a [KG CONTEXT] injection string.

    Returns empty string when no relevant entities are found.
    """
    if not query:
        return ""
    matches = kg_query(query, limit=limit)
    if not matches:
        return ""
    lines = ["[KG CONTEXT — relevant entities from long-term memory]"]
    for e in matches:
        facts_str = ", ".join(f"{k}: {v}" for k, v in e.get("facts", {}).items()) if e.get("facts") else ""
        rels = e.get("relations", [])
        rel_str = "; ".join(f"{r['relation']} → {r['entity']}" for r in rels[:5]) if rels else ""
        parts = [f"• [{e['type']}] {e['name']}"]
        if facts_str:
            parts.append(f"  facts: {facts_str[:200]}")
        if rel_str:
            parts.append(f"  links: {rel_str}")
        lines.extend(parts)
    lines.append("")
    return "\n".join(lines)
