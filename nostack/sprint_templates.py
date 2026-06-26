"""Predefined sprint chains for common workflows."""

from typing import Any

SPRINT_TEMPLATES: dict[str, list[str]] = {
    "feature": ["office-hours", "plan-ceo-review", "plan-eng-review", "review", "qa", "ship"],
    "bugfix": ["investigate", "review", "ship"],
    "security": ["cso", "review", "ship"],
    "design": ["design-consultation", "design-shotgun", "design-html", "design-review"],
    "docs": ["document-generate", "document-release"],
    "release": ["review", "qa", "document-release", "ship", "land-and-deploy", "canary"],
    "retro": ["retro", "learn"],
}

TEMPLATE_METADATA: dict[str, dict[str, Any]] = {
    "feature": {
        "name": "Feature Development",
        "description": "Full feature lifecycle: product interrogation, CEO review, engineering review, code review, QA, and ship.",
        "estimated_steps": 6,
    },
    "bugfix": {
        "name": "Bug Fix",
        "description": "Investigate root cause, review the fix, and ship.",
        "estimated_steps": 3,
    },
    "security": {
        "name": "Security Audit & Fix",
        "description": "CSO security audit, code review of fixes, and ship.",
        "estimated_steps": 3,
    },
    "design": {
        "name": "Design System",
        "description": "Design consultation, shotgun exploration, HTML engineering, and design review.",
        "estimated_steps": 4,
    },
    "docs": {
        "name": "Documentation",
        "description": "Generate documentation from scratch, then release and update all docs.",
        "estimated_steps": 2,
    },
    "release": {
        "name": "Full Release",
        "description": "Code review, QA, docs update, ship, deploy, and canary monitoring.",
        "estimated_steps": 6,
    },
    "retro": {
        "name": "Retrospective",
        "description": "Data-driven retrospective from git history, then capture learnings.",
        "estimated_steps": 2,
    },
}


def list_templates() -> dict[str, Any]:
    """List all available sprint templates with metadata."""
    result: dict[str, Any] = {}
    for key, skills in SPRINT_TEMPLATES.items():
        meta = TEMPLATE_METADATA.get(key, {})
        result[key] = {
            "skills": skills,
            "name": meta.get("name", key.title()),
            "description": meta.get("description", ""),
            "estimated_steps": meta.get("estimated_steps", len(skills)),
        }
    return result


def get_template(name: str) -> dict[str, Any] | None:
    """Get a single sprint template by name."""
    skills = SPRINT_TEMPLATES.get(name)
    if skills is None:
        return None
    meta = TEMPLATE_METADATA.get(name, {})
    return {
        "name": name,
        "skills": skills,
        "display_name": meta.get("name", name.title()),
        "description": meta.get("description", ""),
        "estimated_steps": meta.get("estimated_steps", len(skills)),
    }
