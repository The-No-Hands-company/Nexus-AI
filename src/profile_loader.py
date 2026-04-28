from __future__ import annotations

import os
from functools import lru_cache


_PROFILE_FILES = [
    ("docs/STRATEGY_AND_GUARDRAILS.md", "guardrails", 10),
    ("ARCHITECT.md", "architecture", 20),
    ("USER.md", "user", 30),
    ("SOUL.md", "persona", 40),
    ("AGENT.md", "agent", 50),
    ("AGENTS.md", "agent", 55),
    ("IDENTITY.md", "identity", 60),
    ("SKILL.md", "skill", 70),
]


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, object] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip().strip('"\'') for item in value[1:-1].split(",") if item.strip()]
            meta[key] = items
        elif value.isdigit():
            meta[key] = int(value)
        else:
            meta[key] = value.strip('"\'')
    return meta, body.strip()


@lru_cache(maxsize=32)
def load_profile_pack(persona_name: str = "assistant") -> dict:
    root = os.getcwd()
    parts: list[tuple[int, str, str, str]] = []
    allowed_tools: list[str] | None = None
    for rel_path, default_role, default_priority in _PROFILE_FILES:
        path = os.path.join(root, rel_path)
        if not os.path.exists(path):
            continue
        raw = open(path, "r", encoding="utf-8", errors="ignore").read()
        meta, body = _parse_frontmatter(raw)
        if str(meta.get("safety_mode", "")).lower() == "off":
            continue
        apply_to = meta.get("apply_to", [])
        if apply_to and persona_name not in apply_to:
            continue
        if "allowed_tools" in meta and isinstance(meta["allowed_tools"], list):
            allowed_tools = [str(item) for item in meta["allowed_tools"]]
        priority = int(meta.get("priority", default_priority))
        role = str(meta.get("role", default_role))
        parts.append((priority, os.path.basename(path), role, body.strip()))
    parts.sort(key=lambda item: item[0])
    instructions = "\n\n".join(f"[{name} | role={role}]\n{text}" for _, name, role, text in parts if text)
    return {"persona": persona_name, "instructions": instructions, "allowed_tools": allowed_tools}


def clear_profile_pack_cache() -> None:
    load_profile_pack.cache_clear()


def inspect_profile_pack(persona_name: str = "assistant", base_dir: str | None = None) -> dict:
    root = base_dir or os.getcwd()
    resolved: list[dict] = []
    filtered: list[dict] = []
    for rel_path, default_role, default_priority in _PROFILE_FILES:
        path = os.path.join(root, rel_path)
        exists = os.path.exists(path)
        entry = {"path": rel_path, "role": default_role, "priority": default_priority, "exists": exists}
        if not exists:
            filtered.append({**entry, "reason": "not_found"})
            continue
        raw = open(path, "r", encoding="utf-8", errors="ignore").read()
        meta, _ = _parse_frontmatter(raw)
        if str(meta.get("safety_mode", "")).lower() == "off":
            filtered.append({**entry, "reason": "safety_mode_off"})
            continue
        apply_to = meta.get("apply_to", [])
        if apply_to and persona_name not in apply_to:
            filtered.append({**entry, "reason": "persona_not_in_apply_to"})
            continue
        priority = int(meta.get("priority", default_priority))
        role = str(meta.get("role", default_role))
        resolved.append({"path": rel_path, "role": role, "priority": priority, "exists": True})
    resolved.sort(key=lambda e: e["priority"])
    pack = load_profile_pack(persona_name)
    return {
        "persona": persona_name,
        "instructions": pack["instructions"],
        "allowed_tools": pack["allowed_tools"],
        "resolved_precedence": [e["path"] for e in resolved],
        "filtered_files": filtered,
        "files": resolved,
    }