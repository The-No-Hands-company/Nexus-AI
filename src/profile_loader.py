"""Runtime loader for file-based instruction/persona layers.

Second-pass behavior:
- explicit ingest allowlist
- deterministic precedence (safety/architecture -> user prefs -> persona style)
- frontmatter controls (role, priority, apply_to, safety_mode)
- hard caps on file and merged context size
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _AllowlistEntry:
    rel_path: str
    category: str
    default_role: str
    default_priority: int


_ALLOWLIST: tuple[_AllowlistEntry, ...] = (
    # Safety and architecture constraints first.
    _AllowlistEntry("ARCHITECT.md", "safety_arch", "architecture", 20),
    _AllowlistEntry("docs/ARCHITECTURE.md", "safety_arch", "architecture", 30),
    _AllowlistEntry("docs/STRATEGY_AND_GUARDRAILS.md", "safety_arch", "safety", 10),

    # User intent and preferences.
    _AllowlistEntry("USER.md", "user_pref", "user", 10),
    _AllowlistEntry("IDENTITY.md", "user_pref", "identity", 20),
    _AllowlistEntry("TOOLS.md", "user_pref", "tools", 30),

    # Persona/style layers.
    _AllowlistEntry("SOUL.md", "persona_style", "soul", 10),
    _AllowlistEntry("AGENTS.md", "persona_style", "agent", 20),
    _AllowlistEntry("AGENT.md", "persona_style", "agent", 25),
    _AllowlistEntry("SKILL.md", "persona_style", "skill", 30),
    _AllowlistEntry(".agent.md", "persona_style", "agent", 35),
    _AllowlistEntry(".prompt.md", "persona_style", "prompt", 40),
    _AllowlistEntry("copilot-instructions.md", "persona_style", "instructions", 45),
)

_CATEGORY_ORDER = {
    "safety_arch": 0,
    "user_pref": 1,
    "persona_style": 2,
}

_ROLE_TO_CATEGORY = {
    "safety": "safety_arch",
    "guardrail": "safety_arch",
    "security": "safety_arch",
    "architecture": "safety_arch",
    "constraint": "safety_arch",
    "constraints": "safety_arch",
    "user": "user_pref",
    "preference": "user_pref",
    "preferences": "user_pref",
    "identity": "user_pref",
    "tools": "user_pref",
    "persona": "persona_style",
    "style": "persona_style",
    "agent": "persona_style",
    "soul": "persona_style",
    "skill": "persona_style",
}

_MAX_FILE_BYTES = 64 * 1024
_MAX_FILE_CHARS = 3000
_MAX_MERGED_CHARS = 9000
_CACHE_TTL_SECONDS = 5.0
_CACHE: dict[str, dict[str, Any]] = {}


def clear_profile_pack_cache() -> None:
    _CACHE.clear()


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text

    raw = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip().lower()] = v.strip()
    return meta, body


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _parse_tool_list(value: Any) -> set[str] | None:
    if value is None:
        return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return {str(x).strip() for x in parsed if str(x).strip()}
            except Exception:
                raw = raw[1:-1]
        parts = [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]
        return set(parts) or None

    if isinstance(value, list):
        parsed = {str(x).strip() for x in value if str(x).strip()}
        return parsed or None

    return None


def _extract_markdown_section_tools(body: str) -> set[str] | None:
    m = re.search(r"(?ims)^#{1,6}\s*allowed\s+tools\s*$([\s\S]*?)(?=^#{1,6}\s|\Z)", body)
    if not m:
        return None
    block = m.group(1)
    tools: set[str] = set()
    for line in block.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("-") or t.startswith("*"):
            t = t[1:].strip()
        t = t.strip("` ")
        if t and re.fullmatch(r"[a-zA-Z0-9_\-]+", t):
            tools.add(t)
    return tools or None


def _persona_filter_matches(meta: dict[str, Any], persona_name: str) -> bool:
    if not persona_name:
        return True
    raw = meta.get("persona") or meta.get("persona_id") or meta.get("apply_to")
    if raw is None:
        return True
    allowed = _parse_tool_list(raw)
    if not allowed:
        return True
    return persona_name in allowed or "*" in allowed


def _safety_mode_enabled(meta: dict[str, Any]) -> bool:
    raw = str(meta.get("safety_mode", "advisory")).strip().lower()
    return raw not in {"off", "disabled", "false", "0", "none"}


def _normalize_role(meta: dict[str, Any], default_role: str) -> str:
    raw = str(meta.get("role") or default_role).strip().lower()
    return raw or default_role


def _category_for_role(role: str, fallback_category: str) -> str:
    return _ROLE_TO_CATEGORY.get(role, fallback_category)


def _resolve_roots(base_dir: str | None = None) -> list[str]:
    roots: list[str] = []
    if base_dir:
        roots.append(os.path.abspath(base_dir))
    else:
        roots.append(os.getcwd())

    env_paths = os.getenv("NEXUS_PROFILE_DIRS", "").strip()
    if env_paths:
        for raw in env_paths.split(os.pathsep):
            p = raw.strip()
            if p:
                roots.append(os.path.abspath(p))

    # Preserve order while deduplicating.
    seen: set[str] = set()
    ordered: list[str] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return ordered


def _discover_profile_files(base_dir: str | None = None) -> list[tuple[str, _AllowlistEntry]]:
    files: list[tuple[str, _AllowlistEntry]] = []
    for root in _resolve_roots(base_dir):
        for entry in _ALLOWLIST:
            path = os.path.join(root, entry.rel_path)
            if os.path.isfile(path):
                files.append((path, entry))
    return files


def inspect_profile_pack(base_dir: str | None = None, persona_name: str = "") -> dict[str, Any]:
    cache_key = f"inspect::{os.path.abspath(base_dir) if base_dir else os.getcwd()}::{persona_name}"
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now - float(cached.get("ts", 0.0))) < _CACHE_TTL_SECONDS:
        return dict(cached["value"])

    roots = _resolve_roots(base_dir)
    allowed_tools: set[str] | None = None
    candidates: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []

    for root in roots:
        for entry in _ALLOWLIST:
            path = os.path.join(root, entry.rel_path)
            if not os.path.isfile(path):
                continue

            try:
                size_bytes = os.path.getsize(path)
                if size_bytes > _MAX_FILE_BYTES:
                    filtered.append(
                        {
                            "path": path,
                            "reason": "file_too_large",
                            "size_bytes": size_bytes,
                            "max_size_bytes": _MAX_FILE_BYTES,
                        }
                    )
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    raw = fh.read()
            except Exception as exc:
                filtered.append({"path": path, "reason": "read_error", "detail": str(exc)})
                continue

            meta, body = _parse_frontmatter(raw)

            if not _safety_mode_enabled(meta):
                filtered.append({"path": path, "reason": "safety_mode_disabled"})
                continue

            if not _persona_filter_matches(meta, persona_name):
                filtered.append(
                    {
                        "path": path,
                        "reason": "persona_filtered",
                        "persona": persona_name,
                        "apply_to": str(meta.get("apply_to") or ""),
                    }
                )
                continue

            body = body.strip()
            if not body:
                filtered.append({"path": path, "reason": "empty_body"})
                continue

            file_tools = _parse_tool_list(meta.get("allowed_tools"))
            if file_tools is None:
                file_tools = _extract_markdown_section_tools(body)
            if file_tools:
                allowed_tools = file_tools if allowed_tools is None else (allowed_tools & file_tools)

            role = _normalize_role(meta, entry.default_role)
            category = _category_for_role(role, entry.category)
            priority = _parse_int(meta.get("priority"), entry.default_priority)
            snippet = body[:_MAX_FILE_CHARS]
            safety_mode = str(meta.get("safety_mode", "advisory") or "advisory").strip().lower()

            candidates.append(
                {
                    "path": path,
                    "snippet": snippet,
                    "role": role,
                    "category": category,
                    "priority": priority,
                    "safety_mode": safety_mode,
                    "order_key": [
                        _CATEGORY_ORDER.get(str(category), 99),
                        int(priority),
                        str(path),
                    ],
                }
            )

    candidates.sort(
        key=lambda item: (
            int(item["order_key"][0]),
            int(item["order_key"][1]),
            str(item["order_key"][2]),
        )
    )

    blocks: list[str] = []
    included: list[str] = []
    precedence: list[dict[str, Any]] = []
    total_chars = 0
    for item in candidates:
        remaining = _MAX_MERGED_CHARS - total_chars
        if remaining <= 0:
            filtered.append({"path": item["path"], "reason": "merge_cap_reached"})
            continue
        snippet = str(item["snippet"])[:remaining]
        total_chars += len(snippet)
        blocks.append(
            f"[{os.path.basename(str(item['path']))} | role={item['role']} | category={item['category']} | priority={item['priority']} | safety_mode={item['safety_mode']}]\n{snippet}"
        )
        included.append(str(item["path"]))
        precedence.append(
            {
                "path": str(item["path"]),
                "role": str(item["role"]),
                "category": str(item["category"]),
                "priority": int(item["priority"]),
                "order_key": list(item["order_key"]),
                "safety_mode": str(item["safety_mode"]),
            }
        )

    value = {
        "instructions": "\n\n".join(blocks).strip(),
        "allowed_tools": sorted(allowed_tools) if allowed_tools else None,
        "files": included,
        "resolved_precedence": precedence,
        "filtered_files": filtered,
        "roots": roots,
        "persona": persona_name,
        "caps": {
            "max_file_bytes": _MAX_FILE_BYTES,
            "max_file_chars": _MAX_FILE_CHARS,
            "max_merged_chars": _MAX_MERGED_CHARS,
        },
    }
    _CACHE[cache_key] = {"ts": now, "value": value}
    return dict(value)


def load_profile_pack(base_dir: str | None = None, persona_name: str = "") -> dict[str, Any]:
    inspected = inspect_profile_pack(base_dir=base_dir, persona_name=persona_name)
    return {
        "instructions": str(inspected.get("instructions") or "").strip(),
        "allowed_tools": inspected.get("allowed_tools"),
        "files": list(inspected.get("files") or []),
    }
