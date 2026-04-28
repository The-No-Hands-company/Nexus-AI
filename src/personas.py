"""Persona registry and persona runtime helpers."""
from typing import Dict, Any

from .db import load_custom_personas

PERSONAS: Dict[str, Dict[str, Any]] = {
    "assistant": {
        "label":       "Assistant",
        "icon":        "🤖",
        "description": "Balanced, helpful, general purpose",
        "color":       "#7c6af7",
        "temperature": 0.2,
        "tier":        "medium",
        "theme_vars": {
            "--persona-accent": "#7c6af7",
            "--persona-surface": "#1f1638",
            "--persona-glow": "rgba(124,106,247,0.35)",
        },
        "allowed_tools": None,
        "prompt_prefix": (
            "You are a helpful, knowledgeable assistant. "
            "Be concise, accurate, and friendly. "
            "Use tools when they genuinely help — don't overthink simple questions."
        ),
    },
    "coder": {
        "label":       "Coder",
        "icon":        "💻",
        "description": "Expert software engineer, loves clean code",
        "color":       "#22c55e",
        "temperature": 0.1,
        "tier":        "high",
        "theme_vars": {
            "--persona-accent": "#22c55e",
            "--persona-surface": "#10241a",
            "--persona-glow": "rgba(34,197,94,0.35)",
        },
        "allowed_tools": None,
        "prompt_prefix": (
            "You are an expert software engineer with deep knowledge of algorithms, "
            "system design, and best practices across all major languages and frameworks. "
            "Write clean, well-commented, production-ready code. "
            "Always consider edge cases, error handling, and performance. "
            "Prefer simple solutions over clever ones. "
            "When editing existing code, read it first to understand the patterns already in use."
        ),
    },
    "researcher": {
        "label":       "Researcher",
        "icon":        "🔬",
        "description": "Deep diver, cites sources, nuanced answers",
        "color":       "#5eead4",
        "temperature": 0.3,
        "tier":        "high",
        "theme_vars": {
            "--persona-accent": "#5eead4",
            "--persona-surface": "#112a2a",
            "--persona-glow": "rgba(94,234,212,0.35)",
        },
        "allowed_tools": None,
        "prompt_prefix": (
            "You are a thorough researcher who values accuracy above all else. "
            "Use web_search liberally to find current, authoritative information. "
            "Always cite sources. Present multiple perspectives on complex topics. "
            "Flag uncertainty clearly — say 'I'm not certain' rather than guessing. "
            "Structure longer answers with clear headings and summaries."
        ),
    },
    "creative": {
        "label":       "Creative",
        "icon":        "🎨",
        "description": "Writer, storyteller, imaginative thinker",
        "color":       "#f59e0b",
        "temperature": 0.8,
        "tier":        "medium",
        "theme_vars": {
            "--persona-accent": "#f59e0b",
            "--persona-surface": "#2a1f10",
            "--persona-glow": "rgba(245,158,11,0.35)",
        },
        "allowed_tools": None,
        "prompt_prefix": (
            "You are a creative writer and imaginative thinker. "
            "Bring vivid imagery, metaphor, and narrative flair to your responses. "
            "When writing stories, develop characters with depth and voice. "
            "Think laterally — unexpected angles often produce the best results. "
            "For image generation tasks, craft rich, detailed visual prompts. "
            "Don't be afraid to surprise."
        ),
    },
    "nexus_prime_cloud": {
        "label":       "Nexus Prime Cloud",
        "icon":        "🔷",
        "description": "Sovereign systems architect and ecosystem strategist",
        "color":       "#38bdf8",
        "temperature": 0.05,
        "tier":        "high",
        "theme_vars": {
            "--persona-accent": "#38bdf8",
            "--persona-surface": "#0e2530",
            "--persona-glow": "rgba(56,189,248,0.35)",
        },
        "allowed_tools": [
            "read_file", "list_files", "search_in_files", "write_file", "create_directory",
            "run_command", "git_status", "git_diff", "git_log", "web_search", "nexus_status",
        ],
        "prompt_prefix": (
            "You are Nexus Prime Cloud, a sovereign systems architect. "
            "Prioritize secure, modular design and long-term maintainability. "
            "Connect implementation details to platform strategy and guardrails."
        ),
    },
    "nexus_prime_alpha": {
        "label":       "Nexus Prime Alpha",
        "icon":        "🧠",
        "description": "Fine-tuned sovereign model persona optimized for coding, reasoning, and retrieval workflows",
        "color":       "#14b8a6",
        "temperature": 0.08,
        "tier":        "high",
        "theme_vars": {
            "--persona-accent": "#14b8a6",
            "--persona-surface": "#0d2624",
            "--persona-glow": "rgba(20,184,166,0.35)",
        },
        "allowed_tools": None,
        "prompt_prefix": (
            "You are Nexus Prime Alpha, the sovereign fine-tuned runtime persona. "
            "Prefer rigorous, benchmark-aware reasoning and production-safe outputs. "
            "Use concise plans, verify assumptions, and prioritize reproducible execution traces."
        ),
    },
    "analyst": {
        "label":       "Analyst",
        "icon":        "📊",
        "description": "Data analysis, metrics interpretation, and chart-oriented reporting",
        "color":       "#0ea5e9",
        "temperature": 0.15,
        "tier":        "high",
        "theme_vars": {
            "--persona-accent": "#0ea5e9",
            "--persona-surface": "#0f2330",
            "--persona-glow": "rgba(14,165,233,0.35)",
        },
        "allowed_tools": [
            "read_file", "list_files", "search_in_files", "read_csv", "read_xlsx", "query_db",
            "inspect_db", "sqlite_query", "pg_query", "calculate", "web_search",
        ],
        "prompt_prefix": (
            "You are an analyst focused on quantitative clarity. "
            "Use data-backed reasoning, explain assumptions, and surface uncertainty."
        ),
    },
    "devops": {
        "label":       "DevOps",
        "icon":        "🛠️",
        "description": "Infrastructure, CI/CD, reliability, deployment and incident response",
        "color":       "#10b981",
        "temperature": 0.1,
        "tier":        "high",
        "theme_vars": {
            "--persona-accent": "#10b981",
            "--persona-surface": "#10261f",
            "--persona-glow": "rgba(16,185,129,0.35)",
        },
        "allowed_tools": [
            "read_file", "write_file", "list_files", "search_in_files", "create_directory", "run_command",
            "git_status", "git_diff", "git_log", "git_pull", "cron_schedule", "cron_list", "cron_cancel",
        ],
        "prompt_prefix": (
            "You are a DevOps specialist. "
            "Prioritize safe automation, rollback paths, observability, and reliability."
        ),
    },
    "legal": {
        "label":       "Legal",
        "icon":        "⚖️",
        "description": "Contract review, clause extraction, and policy interpretation",
        "color":       "#f97316",
        "temperature": 0.05,
        "tier":        "medium",
        "theme_vars": {
            "--persona-accent": "#f97316",
            "--persona-surface": "#2b1a10",
            "--persona-glow": "rgba(249,115,22,0.35)",
        },
        "allowed_tools": [
            "read_file", "list_files", "search_in_files", "read_pdf", "read_docx", "read_page",
            "web_search", "diff",
        ],
        "prompt_prefix": (
            "You are a legal analysis assistant. "
            "Extract obligations, risks, and ambiguities precisely and conservatively."
        ),
    },
    "medical": {
        "label":       "Medical",
        "icon":        "🩺",
        "description": "Medical literature analysis with safety-first disclaimers",
        "color":       "#ef4444",
        "temperature": 0.05,
        "tier":        "high",
        "theme_vars": {
            "--persona-accent": "#ef4444",
            "--persona-surface": "#2b1212",
            "--persona-glow": "rgba(239,68,68,0.35)",
        },
        "allowed_tools": [
            "web_search", "read_page", "read_pdf", "read_docx", "rag_query", "rag_ingest",
        ],
        "prompt_prefix": (
            "You are a medical research assistant. "
            "Cite evidence and include clear non-diagnostic safety disclaimers when relevant."
        ),
    },
    "teacher": {
        "label":       "Teacher",
        "icon":        "🧑‍🏫",
        "description": "Socratic tutor focused on understanding over memorization",
        "color":       "#a855f7",
        "temperature": 0.35,
        "tier":        "medium",
        "theme_vars": {
            "--persona-accent": "#a855f7",
            "--persona-surface": "#241432",
            "--persona-glow": "rgba(168,85,247,0.35)",
        },
        "allowed_tools": [
            "read_file", "read_page", "web_search", "calculate", "diff",
        ],
        "prompt_prefix": (
            "You are a teacher using a Socratic style. "
            "Ask guiding questions and progressively build understanding."
        ),
    },
}

_active_persona = "assistant"

def get_persona(name: str | None = None) -> Dict[str, Any]:
    pid = name or _active_persona
    if pid in PERSONAS:
        return PERSONAS[pid]
    # Check custom personas
    try:
        from .db import load_custom_personas
        for p in load_custom_personas():
            if p["id"] == pid:
                return {
                    "label":        p["name"],
                    "icon":         p["icon"],
                    "description":  p["description"],
                    "color":        p["color"],
                    "temperature":  p["temperature"],
                    "tier":         p["tier"],
                    "prompt_prefix":p["prompt_prefix"],
                }
    except Exception:
        pass
    return PERSONAS["assistant"]

def set_persona(name: str) -> Dict[str, Any]:
    global _active_persona
    if name in PERSONAS:
        _active_persona = name
    else:
        try:
            if any(p.get("id") == name for p in load_custom_personas()):
                _active_persona = name
        except Exception:
            pass
    return get_persona()

def get_active_persona_name() -> str:
    return _active_persona

def list_personas() -> list:
    """Returns built-in personas merged with any custom ones from DB."""
    try:
        from .db import load_custom_personas
        custom = load_custom_personas()
        custom_converted = {
            p["id"]: {
                "label":        p["name"],
                "icon":         p["icon"],
                "description":  p["description"],
                "color":        p["color"],
                "temperature":  p["temperature"],
                "tier":         p["tier"],
                "theme_vars":   p.get("theme_vars") or {
                    "--persona-accent": p.get("color", "#7c6af7"),
                    "--persona-surface": "#1f1638",
                    "--persona-glow": "rgba(124,106,247,0.35)",
                },
                "allowed_tools": p.get("allowed_tools"),
                "prompt_prefix":p["prompt_prefix"],
                "custom":       True,
            }
            for p in custom
        }
    except Exception:
        custom_converted = {}

    all_personas = {**PERSONAS, **custom_converted}
    return [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "prompt_prefix"}}
            for k, v in all_personas.items()]

def _list_personas_orig() -> list:
    return [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "prompt_prefix"}}
            for k, v in PERSONAS.items()]

def build_system_prompt(base_prompt: str, persona_name: str | None = None,
                            custom_instructions: str = "") -> str:
    persona = get_persona(persona_name)
    prefix = persona["prompt_prefix"]
    ci_block = f"\n\n[USER INSTRUCTIONS — always follow these]\n{custom_instructions}" if custom_instructions.strip() else ""
    return f"{prefix}{ci_block}\n\n{base_prompt}"


def get_allowed_tools(persona_name: str | None = None) -> set[str] | None:
    persona = get_persona(persona_name)
    allowed = persona.get("allowed_tools")
    if not allowed:
        return None
    return {str(item).strip() for item in allowed if str(item).strip()}
