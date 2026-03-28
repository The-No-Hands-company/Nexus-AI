"""
Agent personas — each has a system prompt prefix, temperature default,
preferred provider tier, and UI accent color.
"""
from typing import Dict, Any

PERSONAS: Dict[str, Dict[str, Any]] = {
    "assistant": {
        "label":       "Assistant",
        "icon":        "🤖",
        "description": "Balanced, helpful, general purpose",
        "color":       "#7c6af7",
        "temperature": 0.2,
        "tier":        "medium",
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
        "prompt_prefix": (
            "You are a creative writer and imaginative thinker. "
            "Bring vivid imagery, metaphor, and narrative flair to your responses. "
            "When writing stories, develop characters with depth and voice. "
            "Think laterally — unexpected angles often produce the best results. "
            "For image generation tasks, craft rich, detailed visual prompts. "
            "Don't be afraid to surprise."
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
        from db import load_custom_personas
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
    return get_persona()

def get_active_persona_name() -> str:
    return _active_persona

def list_personas() -> list:
    """Returns built-in personas merged with any custom ones from DB."""
    try:
        from db import load_custom_personas
        custom = load_custom_personas()
        custom_converted = {
            p["id"]: {
                "label":        p["name"],
                "icon":         p["icon"],
                "description":  p["description"],
                "color":        p["color"],
                "temperature":  p["temperature"],
                "tier":         p["tier"],
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
