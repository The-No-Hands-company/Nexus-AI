from __future__ import annotations

from typing import Any


_PERSONAS: dict[str, dict[str, Any]] = {
    "assistant": {
        "id": "assistant",
        "label": "Assistant",
        "description": "General-purpose helpful assistant.",
        "theme_vars": {"accent": "#2f6fed", "surface": "#f7f9fc"},
        "allowed_tools": None,
    },
    "nexus_prime_cloud": {
        "id": "nexus_prime_cloud",
        "label": "Nexus Prime Cloud",
        "description": "Cloud platform operator.",
        "theme_vars": {"accent": "#0a7b83", "surface": "#eef8f9"},
        "allowed_tools": None,
    },
    "analyst": {
        "id": "analyst",
        "label": "Analyst",
        "description": "Evidence-first analysis persona.",
        "theme_vars": {"accent": "#6b7280", "surface": "#f5f5f5"},
        "allowed_tools": ["read_file", "list_files", "web_search", "read_pdf"],
    },
    "devops": {
        "id": "devops",
        "label": "DevOps",
        "description": "Infrastructure and deployment operations.",
        "theme_vars": {"accent": "#0f766e", "surface": "#ecfeff"},
        "allowed_tools": None,
    },
    "legal": {
        "id": "legal",
        "label": "Legal",
        "description": "Conservative compliance reviewer.",
        "theme_vars": {"accent": "#7c3aed", "surface": "#f5f3ff"},
        "allowed_tools": ["read_file", "list_files", "read_pdf", "web_search"],
    },
    "medical": {
        "id": "medical",
        "label": "Medical",
        "description": "High-safety medical information persona.",
        "theme_vars": {"accent": "#dc2626", "surface": "#fff1f2"},
        "allowed_tools": ["read_file", "list_files", "web_search"],
    },
    "teacher": {
        "id": "teacher",
        "label": "Teacher",
        "description": "Educational explainer persona.",
        "theme_vars": {"accent": "#ca8a04", "surface": "#fefce8"},
        "allowed_tools": None,
    },
    "coder": {
        "id": "coder",
        "label": "Coder",
        "description": "Code-centric builder persona.",
        "theme_vars": {"accent": "#2563eb", "surface": "#eff6ff"},
        "allowed_tools": None,
    },
    "general": {
        "id": "general",
        "label": "General",
        "description": "Default general persona.",
        "theme_vars": {"accent": "#111827", "surface": "#f9fafb"},
        "allowed_tools": None,
    },
}

_ACTIVE_PERSONA = "assistant"


def list_personas() -> list[dict[str, Any]]:
    return [dict(item) for item in _PERSONAS.values()]


def set_persona(name: str) -> bool:
    global _ACTIVE_PERSONA
    if name not in _PERSONAS:
        return False
    _ACTIVE_PERSONA = name
    return True


def get_active_persona_name() -> str:
    return _ACTIVE_PERSONA


def get_persona(name: str | None = None) -> dict[str, Any]:
    key = name or _ACTIVE_PERSONA
    return dict(_PERSONAS.get(key, _PERSONAS["assistant"]))


def get_allowed_tools(persona_name: str | None = None) -> list[str] | None:
    return get_persona(persona_name).get("allowed_tools")


def build_system_prompt(persona_name: str | None = None, extra: str = "") -> str:
    persona = get_persona(persona_name)
    text = f"You are Nexus AI operating as {persona['label']}. {persona['description']}"
    if extra:
        text += f"\n\n{extra}"
    return text