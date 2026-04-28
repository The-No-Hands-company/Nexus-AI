from __future__ import annotations

import time
from typing import Any


_entities: dict[str, dict[str, Any]] = {}
_edges: list[dict[str, Any]] = []


def kg_store(
    entity_id: str,
    entity_type: str | dict[str, Any] | None = None,
    payload: dict[str, Any] | list[Any] | None = None,
    relations: list[Any] | None = None,
    *,
    facts: dict[str, Any] | None = None,
) -> str:
    """Store an entity. Accepts several calling conventions:
    - kg_store(id, entity_type_str, facts_dict, relations_list)  ← tools_builtin usage
    - kg_store(id, entity_type_str, payload_dict)                ← test usage
    - kg_store(id, payload_dict)                                 ← legacy usage
    - kg_store(id, entity_type=..., facts=..., ...)              ← keyword usage
    Returns the entity_id string.
    """
    # Normalise overloaded second positional arg
    if isinstance(entity_type, dict):
        # Called as kg_store(id, payload_dict) — shift args
        payload = entity_type
        entity_type = (payload or {}).pop("entity_type", "concept")
    elif entity_type is None:
        entity_type = "concept"

    # Third arg may be a facts dict or a payload dict
    if isinstance(payload, list):
        # Called as kg_store(id, entity_type, relations_list) — unlikely but safe
        relations = payload
        payload = {}
    elif payload is None:
        payload = {}

    resolved_facts = facts or (payload.pop("facts", {}) if isinstance(payload, dict) else {})
    resolved_relations = relations or (payload.pop("relations", []) if isinstance(payload, dict) else [])

    record = {
        "id": entity_id,
        "name": entity_id,
        "entity_type": str(entity_type),
        "facts": resolved_facts,
        "relations": resolved_relations,
        **(payload if isinstance(payload, dict) else {}),
        "updated_at": time.time(),
    }
    _entities[entity_id] = record
    return entity_id
    return record


def kg_get(entity_id: str) -> dict[str, Any] | None:
    return _entities.get(entity_id)


def kg_list_entities(entity_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    items = list(_entities.values())
    if entity_type:
        wanted = str(entity_type).strip().lower()
        items = [it for it in items if str(it.get("entity_type", "")).strip().lower() == wanted]
    return items[:limit]


def kg_query(query: str, limit: int = 10) -> list[dict[str, Any]]:
    needle = (query or "").lower()
    results = []
    for item in _entities.values():
        haystack = f"{item.get('id', '')} {item.get('text', '')} {item.get('content', '')}".lower()
        if needle in haystack:
            results.append(item)
    return results[:limit]


def kg_delete(entity_id: str) -> bool:
    return _entities.pop(entity_id, None) is not None


def kg_graph(limit: int = 500) -> dict[str, Any]:
    nodes = list(_entities.values())[:limit]
    return {"nodes": nodes, "edges": list(_edges)}


def kg_merge(source_id: str, target_id: str) -> dict[str, Any]:
    source = _entities.get(source_id)
    target = _entities.get(target_id)
    if not source or not target:
        return {"merged": False}
    target.setdefault("aliases", []).append(source_id)
    _entities.pop(source_id, None)
    return {"merged": True, "target": target}


_NT_TRIPLE_RE = None  # compiled lazily


def _parse_ntriples(text: str, limit: int) -> tuple[list[dict], list[dict]]:
    """Very lightweight N-Triples parser (subject predicate object .) for import."""
    import re
    global _NT_TRIPLE_RE
    if _NT_TRIPLE_RE is None:
        _NT_TRIPLE_RE = re.compile(
            r'<([^>]+)>\s+<([^>]+)>\s+(<[^>]+>|"[^"]*")\s*\.'
        )
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    for m in _NT_TRIPLE_RE.finditer(text):
        if len(edges) >= limit:
            break
        subj, pred, obj = m.group(1), m.group(2), m.group(3).strip('<>"')
        if subj not in seen_nodes:
            seen_nodes.add(subj)
            nodes.append({"id": subj, "entity_type": "resource"})
        edges.append({"from": subj, "to": obj, "rel": pred})
    return nodes, edges


def kg_import_ontology(
    data: dict[str, Any] | str,
    fmt: str = "auto",
    limit: int = 2000,
) -> dict[str, Any]:
    import json as _json
    nodes: list[dict] = []
    edges_in: list[dict] = []
    triples_processed = 0

    if isinstance(data, str):
        raw = data
        # Try N-Triples / Turtle heuristic: lines ending with " ."
        if (fmt in ("auto", "ntriples", "turtle")) and " ." in raw:
            nodes, edges_in = _parse_ntriples(raw, limit)
            triples_processed = len(edges_in)
        if triples_processed == 0:
            # Try JSON
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, dict):
                    nodes = parsed.get("nodes", [])[:limit]
                    edges_in = parsed.get("edges", [])
                    triples_processed = len(nodes) + len(edges_in)
            except Exception:
                # Plain text fallback
                nodes = [{"id": f"imported-{len(_entities)+1}", "content": raw[:limit]}]
                triples_processed = 1
    elif isinstance(data, dict):
        nodes = data.get("nodes", [])[:limit]
        edges_in = data.get("edges", [])
        triples_processed = len(nodes) + len(edges_in)

    for node in nodes:
        node_id = str(node.get("id") or f"node-{len(_entities) + 1}")
        kg_store(node_id, node)
    for edge in edges_in:
        _edges.append(dict(edge))

    result = kg_graph()
    result["triples_processed"] = triples_processed
    return result


def kg_hybrid_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    return kg_query(query, limit=limit)


def kg_to_context_string(graph: Any, limit: int | None = None, **kwargs: Any) -> str:
    if not graph:
        return ""
    if isinstance(graph, str):
        return graph
    if isinstance(graph, dict):
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
    else:
        nodes = graph
        edges = []
    if limit is not None and limit > 0:
        nodes = list(nodes)[:limit]
        edges = list(edges)[:limit]
    node_lines = []
    for item in nodes:
        if isinstance(item, dict):
            node_lines.append(f"- {item.get('id', '?')}: {item.get('thought') or item.get('text') or item.get('content') or ''}")
        else:
            node_lines.append(f"- {str(item)}")
    edge_lines = [f"- {edge.get('from')} -> {edge.get('to')} ({edge.get('relation', 'related')})" for edge in edges]
    return "\n".join(["Nodes:", *node_lines, "Edges:", *edge_lines]).strip()