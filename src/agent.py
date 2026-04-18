import os, re, json, glob, time, subprocess, threading, resource
from functools import lru_cache
from datetime import datetime, timezone
from contextlib import nullcontext
from typing import Dict, Any, List, Iterator, Optional
from .tools_builtin import dispatch_builtin
from .autonomy import Orchestrator, classify_subtask, PlanningSystem
from .personas import build_system_prompt, get_active_persona_name, get_persona
from .thinking import (
    build_tot_prompt,
    parse_tot_response,
    build_critique_prompt,
    parse_critique_response,
    build_got_prompt,
    parse_got_response,
    run_mcts_planning,
)
from .context_window import ContextWindowManager
from .ensemble import call_llm_ensemble, is_high_risk, score_task_risk, get_ensemble_enabled, set_ensemble_enabled
from .db import load_custom_instructions, log_usage, init_usage_table, add_safety_audit_entry
from .knowledge_graph import kg_to_context_string
from .execution_trace import save_checkpoint as _save_checkpoint
from .safety_pipeline import SAFETY_POLICY_PROFILES, describe_block, screen_output, screen_tool_action
from .safety_types import SafetyAction
from .approvals import create_tool_approval, list_tool_approvals, decide_tool_approval, consume_approved_action
from .memory import add_memory, summarize_history as _summarize_history, get_memory_context
from .secrets_manager import get_secret, inject_request_credentials, secret_access_context
try:
    init_usage_table()
except Exception:
    pass

# ── runtime config ────────────────────────────────────────────────────────────
_config: Dict[str, Any] = {
    "provider":           os.getenv("PROVIDER", "auto").lower(),
    "model":              os.getenv("LLM_MODEL", ""),
    "temperature":        float(os.getenv("LLM_TEMPERATURE", "0.2")),
    "persona":            os.getenv("PERSONA", "general"),
    "ensemble_mode":      True,
    "ensemble_threshold": 0.4,
    "hitl_approval_mode": os.getenv("HITL_APPROVAL_MODE", "off").lower(),
    "safety_profile":     os.getenv("SAFETY_POLICY_PROFILE", "standard").lower(),
}
def get_config() -> Dict[str, Any]: return dict(_config)
def update_config(provider=None, model=None, temperature=None, persona=None,
                  ensemble_mode=None, ensemble_threshold=None, hitl_approval_mode=None,
                  safety_profile=None):
    if provider           is not None: _config["provider"]           = provider.lower()
    if model              is not None: _config["model"]              = model
    if temperature        is not None: _config["temperature"]        = float(temperature)
    if persona            is not None: _config["persona"]            = persona
    if ensemble_mode      is not None:
        _config["ensemble_mode"] = bool(ensemble_mode)
        set_ensemble_enabled(bool(ensemble_mode))
    if ensemble_threshold is not None:
        _config["ensemble_threshold"] = float(ensemble_threshold)
    if hitl_approval_mode is not None:
        mode = str(hitl_approval_mode).lower().strip()
        _config["hitl_approval_mode"] = mode if mode in ("off", "warn", "block") else "off"
    if safety_profile is not None:
        profile = str(safety_profile).lower().strip()
        _config["safety_profile"] = profile if profile in SAFETY_POLICY_PROFILES else "standard"
    return dict(_config)

# ── env ───────────────────────────────────────────────────────────────────────
GH_TOKEN    = os.getenv("GH_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
MAX_LOOP    = 16
COOLDOWN_SECONDS = int(os.getenv("RATE_LIMIT_COOLDOWN", "60"))

# ── Swarm View activity log ───────────────────────────────────────────────────
_MAX_ACTIVITY = 500
activity_log: List[Dict] = []

def _push_activity(event: Dict) -> None:
    """Append *event* to the circular activity log; trim if over cap."""
    activity_log.append(event)
    if len(activity_log) > _MAX_ACTIVITY:
        del activity_log[:-_MAX_ACTIVITY]

# ── Safety audit log ─────────────────────────────────────────────────────────
_MAX_SAFETY_LOG = 1000
safety_log: List[Dict] = []

def _push_safety_event(event_type: str, detail: Dict) -> None:
    """Append a safety audit event.  event_type: 'block' | 'profile_change' | 'pii_scrub'."""
    entry = {
        "ts": time.time(),
        "type": event_type,
        **detail,
    }
    safety_log.append(entry)
    if len(safety_log) > _MAX_SAFETY_LOG:
        del safety_log[:-_MAX_SAFETY_LOG]
    try:
        add_safety_audit_entry(entry)
    except Exception:
        # Keep runtime safety logging resilient even if persistence is unavailable.
        pass

# ── token extraction from user messages ───────────────────────────────────────
_TOKEN_RE   = re.compile(r'gh[ps]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{80,}')
_GITHUB_URL_RE = re.compile(r'https://github\.com/[\w\-\.]+/[\w\-\.]+')
_CLONE_INTENT_RE = re.compile(
    r'\b(clone|develop|continue|work on|improve|build|update|fix|create)\b',
    re.IGNORECASE)

def extract_token(text: str) -> Optional[str]:
    m = _TOKEN_RE.search(text)
    return m.group(0) if m else None

def mask_token(text: str) -> str:
    """Replace tokens with a placeholder so they never reach the LLM."""
    return _TOKEN_RE.sub('[GITHUB_TOKEN_REDACTED]', text)

# ── session working directories ───────────────────────────────────────────────
# sid → {"dir": "/tmp/session_xxx", "token": "ghp_...", "repos": [...]}
_session_state: Dict[str, Dict] = {}

def get_session_state(sid: str) -> Dict:
    if sid not in _session_state:
        _session_state[sid] = {
            "dir":           f"/tmp/ca_session_{sid[:8]}",
            "token":         GH_TOKEN,
            "repos":         [],    # list of cloned repo URLs in this session
            "active_repo":   None,  # most recently cloned/worked-on repo URL
            "safety_profile": None, # None = inherit global _config["safety_profile"]
        }
        os.makedirs(_session_state[sid]["dir"], exist_ok=True)
    return _session_state[sid]

def set_session_repo(sid: str, url: str) -> None:
    """Track which repo the agent is currently working on."""
    s = get_session_state(sid)
    if url and url not in s["repos"]:
        s["repos"].append(url)
    s["active_repo"] = url

def get_session_repo(sid: str) -> str:
    """Return the active repo URL for this session (never the Nexus AI default)."""
    return get_session_state(sid).get("active_repo") or ""

def set_session_token(sid: str, token: str):
    s = get_session_state(sid)
    s["token"] = token

def get_session_token(sid: str) -> str:
    return get_session_state(sid).get("token", GH_TOKEN)

def get_session_dir(sid: str) -> str:
    return get_session_state(sid)["dir"]

def get_session_safety_profile(sid: str) -> str:
    """Return the effective safety profile for *sid*: session override if set, else global config."""
    session_profile = get_session_state(sid).get("safety_profile") if sid else None
    return session_profile or _config.get("safety_profile", "standard")

def set_session_safety_profile(sid: str, profile: str) -> None:
    """Set a per-session safety profile override.  Pass None to clear (revert to global)."""
    get_session_state(sid)["safety_profile"] = profile

# ── provider registry ─────────────────────────────────────────────────────────
PROVIDERS: Dict[str, Dict] = {
    "llm7":    {"label":"LLM7.io","base_url":"https://api.llm7.io/v1",
                "env_key":"LLM7_API_KEY","default_model":"deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
                "openai_compat":True,"keyless":True},
    "groq":    {"label":"Groq","base_url":"https://api.groq.com/openai/v1",
                "env_key":"GROQ_API_KEY","default_model":"llama-3.3-70b-versatile",
                "openai_compat":True},
    "cerebras":{"label":"Cerebras","base_url":"https://api.cerebras.ai/v1",
                "env_key":"CEREBRAS_API_KEY","default_model":"llama-3.3-70b",
                "openai_compat":True},
    "gemini":  {"label":"Google Gemini",
                "base_url":"https://generativelanguage.googleapis.com/v1beta/openai",
                "env_key":"GEMINI_API_KEY","default_model":"gemini-2.0-flash",
                "openai_compat":True},
    "mistral": {"label":"Mistral AI","base_url":"https://api.mistral.ai/v1",
                "env_key":"MISTRAL_API_KEY","default_model":"mistral-small-latest",
                "openai_compat":True},
    "openrouter":{"label":"OpenRouter","base_url":"https://openrouter.ai/api/v1",
                  "env_key":"OPENROUTER_API_KEY",
                  "default_model":"meta-llama/llama-3.3-70b-instruct:free",
                  "openai_compat":True},
    "nvidia":  {"label":"NVIDIA NIM","base_url":"https://integrate.api.nvidia.com/v1",
                "env_key":"NVIDIA_API_KEY","default_model":"meta/llama-3.3-70b-instruct",
                "openai_compat":True},
    "cohere":  {"label":"Cohere","base_url":"https://api.cohere.com/compatibility/v1",
                "env_key":"COHERE_API_KEY","default_model":"command-r-plus",
                "openai_compat":True},
    "github_models":{"label":"GitHub Models",
                     "base_url":"https://models.inference.ai.azure.com",
                     "env_key":"GITHUB_MODELS_TOKEN",
                     "default_model":"meta-llama/Llama-3.3-70B-Instruct",
                     "openai_compat":True},
    "grok":    {"label":"Grok (xAI)","env_key":"GROK_API_KEY",
                "default_model":"grok-3","openai_compat":False},
    "claude":  {"label":"Claude (Anthropic)","env_key":"CLAUDE_API_KEY",
                "default_model":"claude-sonnet-4-20250514","openai_compat":False},
    "ollama":  {"label":"Ollama (Local)","base_url": os.getenv("OLLAMA_BASE_URL","http://localhost:11434/v1"),
                "env_key":"","default_model":"glm-5.1:cloud","openai_compat":True,"keyless":True,"local":True},
}

# ── complexity + provider routing ─────────────────────────────────────────────
PROVIDER_TIERS = {
    "high":   ["ollama","claude","grok","gemini","openrouter","mistral"],
    "medium": ["groq","cerebras","cohere","github_models","nvidia"],
    "low":    ["llm7","groq","cerebras"],
}

# ── budget-aware routing ───────────────────────────────────────────────────────
# Approximate cost in USD per 1K output tokens (used for budget-tier filtering)
_PROVIDER_COST_PER_1K_TOKENS: Dict[str, float] = {
    "ollama":        0.000,
    "llm7":          0.000,
    "github_models": 0.000,
    "groq":          0.001,
    "cerebras":      0.001,
    "cohere":        0.002,
    "mistral":       0.002,
    "nvidia":        0.003,
    "gemini":        0.004,
    "openrouter":    0.005,
    "grok":          0.010,
    "claude":        0.015,
}
BUDGET_TIER: str = os.getenv("BUDGET_TIER", "any").lower()   # free | low | medium | any
_BUDGET_MAX_COST: Dict[str, float] = {
    "free":   0.000,
    "low":    0.002,
    "medium": 0.008,
    "any":    999.0,
}

# ── Mixture-of-Experts specialization routing ─────────────────────────────────
PROVIDER_SPECIALIZATIONS: Dict[str, List[str]] = {
    "coding":    ["ollama", "claude", "groq", "cerebras", "github_models"],
    "research":  ["gemini", "grok", "openrouter", "claude", "mistral"],
    "creative":  ["claude", "gemini", "mistral", "openrouter"],
    "reasoning": ["ollama", "claude", "grok", "gemini"],
}
_CODING_RE   = re.compile(
    r'\b(code|function|class|module|implement|debug|test|refactor|type\s*hint|'
    r'fix.*bug|unit\s*test|write.*test|write.*file|build.*app|api|cli)\b', re.IGNORECASE)
_RESEARCH_RE = re.compile(
    r'\b(research|explain|summarize|compare|analyze|review|source|cite|'
    r'find|what\s+is|how\s+does|why\s+does|read\s+page|web\s+search)\b', re.IGNORECASE)
_CREATIVE_RE = re.compile(
    r'\b(story|poem|image|design|imagine|draw|generate\s+image|creative|'
    r'write.*story|brainstorm|logo|art)\b', re.IGNORECASE)
_REASONING_RE = re.compile(
    r'\b(reason|plan|architect|decide|strategy|think|solve|complex|hard)\b', re.IGNORECASE)


def _task_specialization(task: str) -> Optional[str]:
    """Return the specialization bucket for a task, or None."""
    if _CODING_RE.search(task):   return "coding"
    if _RESEARCH_RE.search(task): return "research"
    if _CREATIVE_RE.search(task): return "creative"
    if _REASONING_RE.search(task): return "reasoning"
    return None


_HIGH_RE = re.compile(
    r'\b(develop|implement|architect|refactor|build|create|design|'
    r'clone.*repo|continue.*development|add.*feature|fix.*bug|'
    r'write.*tests?|full.*stack|entire|complete|production|new.*project)\b',
    re.IGNORECASE)
_MED_RE = re.compile(
    r'\b(explain|summarize|compare|analyze|review|suggest|improve|'
    r'read.*file|list.*files|search|find|what does)\b', re.IGNORECASE)

# ── self-critique config ──────────────────────────────────────────────────────
CRITIQUE_THRESHOLD = float(os.getenv("CRITIQUE_THRESHOLD", "0.75"))


@lru_cache(maxsize=1)
def _cpu_count() -> int:
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


_RESOURCE_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}


def get_system_resources(max_age_seconds: int = 10) -> Dict[str, Any]:
    """Best-effort local resource probe used for adaptive model/provider routing."""
    now = time.time()
    cached = _RESOURCE_CACHE.get("data")
    if cached is not None and now - float(_RESOURCE_CACHE.get("ts", 0.0)) < max_age_seconds:
        return cached

    total_kb = 0
    avail_kb = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
    except Exception:
        pass

    total_gb = round(total_kb / (1024 * 1024), 2) if total_kb else None
    available_gb = round(avail_kb / (1024 * 1024), 2) if avail_kb else None

    load_1m = None
    try:
        load_1m = os.getloadavg()[0]
    except Exception:
        pass

    cpu_count = _cpu_count()
    cpu_load_ratio = round(load_1m / max(cpu_count, 1), 3) if load_1m is not None else None

    data = {
        "total_ram_gb": total_gb,
        "available_ram_gb": available_gb,
        "cpu_count": cpu_count,
        "load_1m": load_1m,
        "cpu_load_ratio": cpu_load_ratio,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _RESOURCE_CACHE["ts"] = now
    _RESOURCE_CACHE["data"] = data
    return data


def _resource_tier(resources: Dict[str, Any]) -> str:
    """Convert local resource snapshot to a routing tier hint."""
    available = resources.get("available_ram_gb")
    load_ratio = resources.get("cpu_load_ratio")

    if available is not None and available < 2.0:
        return "constrained"
    if available is not None and available < 4.0:
        return "low"
    if load_ratio is not None and load_ratio > 1.5:
        return "low"
    return "normal"


def _requires_hitl_checkpoint(kind: str, action: Dict[str, Any], threat: str) -> bool:
    high_risk_tools = {"run_command", "delete_file", "commit_push", "create_repo"}
    if kind in high_risk_tools:
        return True
    if threat in ("high", "critical"):
        return True
    return False


_COMPLEXITY_STEP_RE = re.compile(
    r"\b(first|second|third|then|after that|finally|next|step\s+\d+|steps?|rollback|monitoring)\b",
    re.IGNORECASE,
)
_COMPLEXITY_SYSTEM_RE = re.compile(
    r"\b(production|deploy|migration|database|schema|auth|security|billing|payments?|rollback|incident|monitoring|slo|sre)\b",
    re.IGNORECASE,
)
_COMPLEXITY_SCOPE_RE = re.compile(
    r"\b(end-to-end|full stack|entire|complete|architecture|architect|orchestrate|parallel|multi-step|cross-service)\b",
    re.IGNORECASE,
)


def _build_complexity_profile(task: str) -> Dict[str, Any]:
    source = task or ""
    words = re.findall(r"\w+", source)
    lines = len([line for line in source.splitlines() if line.strip()]) or (1 if source else 0)
    specialization = _task_specialization(source)
    score = 0
    signals: List[str] = []

    if len(words) >= 20:
        score += 1
        signals.append("long_prompt")
    if len(source) >= 160:
        score += 1
        signals.append("dense_prompt")
    if lines >= 3:
        score += 1
        signals.append("multi_line")
    if len(_COMPLEXITY_STEP_RE.findall(source)) >= 2:
        score += 2
        signals.append("multi_step")
    if _COMPLEXITY_SYSTEM_RE.search(source):
        score += 2
        signals.append("system_risk")
    if _COMPLEXITY_SCOPE_RE.search(source):
        score += 1
        signals.append("broad_scope")
    if specialization in ("coding", "reasoning") and len(source) >= 100:
        score += 1
        signals.append(f"{specialization}_depth")
    if "```" in source or any(tok in source for tok in ("src/", ".py", ".ts", "{")):
        score += 1
        signals.append("artifact_context")

    if score >= 5 or len(words) >= 80:
        label = "high"
    elif score >= 2:
        label = "medium"
    else:
        label = "low"

    return {
        "label": label,
        "score": score,
        "word_count": len(words),
        "line_count": lines,
        "specialization": specialization,
        "signals": signals,
    }


def _score_complexity(task: str) -> str:
    return _build_complexity_profile(task).get("label", "low")


def _auto_mcts_guidance(task: str) -> Dict[str, Any] | None:
    profile = _build_complexity_profile(task)
    if profile.get("label") != "high":
        return None
    if profile.get("specialization") not in ("coding", "reasoning", None):
        return None

    providers_used: List[str] = []

    def _llm_fn(prompt: str) -> str:
        result, provider = call_llm_with_fallback([{"role": "user", "content": prompt}], task)
        providers_used.append(provider)
        return result.get("content") or str(result)

    try:
        plan = run_mcts_planning(task, llm_fn=_llm_fn, iterations=6, max_depth=4, branching=3)
    except Exception:
        return None

    best_plan = plan.get("best_plan") or []
    if not best_plan:
        return None
    return {
        "complexity_profile": profile,
        "providers": providers_used,
        "best_plan": best_plan,
        "best_score": plan.get("best_score", 0.0),
        "best_rationale": plan.get("best_rationale", ""),
    }

# ── Ollama model registry (Phase 1: auto-select best model by task type) ─────
# Maps task-type → ordered list of preferred Ollama model names.
# The first model found locally wins; falls back to the configured default.
OLLAMA_MODEL_PREFERENCES: Dict[str, List[str]] = {
    "coding": [
        "qwen2.5-coder:32b", "qwen2.5-coder:14b", "qwen2.5-coder:7b",
        "deepseek-coder-v2:16b", "deepseek-coder:6.7b",
        "codellama:34b", "codellama:13b", "codellama:7b",
        "starcoder2:15b", "starcoder2:7b",
        "glm-5.1:cloud",
    ],
    "reasoning": [
        "deepseek-r1:70b", "deepseek-r1:32b", "deepseek-r1:14b", "deepseek-r1:7b",
        "qwq:32b", "llama3.3:70b", "llama3.1:70b",
        "mistral-nemo:12b", "phi4:14b",
        "glm-5.1:cloud",
    ],
    "research": [
        "llama3.3:70b", "llama3.1:70b", "qwen2.5:72b", "gemma3:27b",
        "mistral-nemo:12b", "phi4:14b",
        "glm-5.1:cloud",
    ],
    "creative": [
        "llama3.1:70b", "mistral:7b", "gemma3:27b", "phi4:14b",
        "glm-5.1:cloud",
    ],
    "data": [
        "deepseek-r1:32b", "qwen2.5:72b", "llama3.1:70b",
        "codellama:34b",
        "glm-5.1:cloud",
    ],
    "general": [
        "llama3.3:70b", "llama3.1:70b", "qwen2.5:72b", "gemma3:27b",
        "mistral-nemo:12b", "phi4:14b",
        "glm-5.1:cloud",
    ],
}

# Vision-capable Ollama models — tried in priority order when request contains images
OLLAMA_VISION_MODELS: List[str] = [
    "llava:34b", "llava:13b", "llava:7b",
    "qwen2-vl:7b", "llava-llama3:8b",
    "llava-phi3:3.8b", "minicpm-v:8b",
    "moondream:1.8b", "bakllava:7b",
]

# Additional cloud-model aliases usable when a provider sends a specific model name
EXTENDED_MODEL_ALIASES: Dict[str, str] = {
    # Ollama pull name → canonical ID used in routing
    "qwen2.5-coder:32b":      "qwen2.5-coder-32b",
    "deepseek-r1:70b":        "deepseek-r1-70b",
    "llama3.3:70b":           "llama-3.3-70b",
    "gemma3:27b":             "gemma-3-27b",
    "phi4:14b":               "phi-4-14b",
    "mistral-nemo:12b":       "mistral-nemo-12b",
}


def get_best_ollama_model(task_type: str) -> str:
    """Return the best locally-available Ollama model for *task_type*.

    Queries the local Ollama API to discover pulled models, then selects the
    highest-priority match from OLLAMA_MODEL_PREFERENCES.  Falls back to the
    configured default if nothing is found.
    """
    preference_list = OLLAMA_MODEL_PREFERENCES.get(task_type, OLLAMA_MODEL_PREFERENCES["general"])
    ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    try:
        import requests as _req
        resp = _req.get(f"{ollama_base}/models", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            # OpenAI-compat: {"data": [{"id": "model:tag"}, ...]}
            available = {m["id"].lower() for m in data.get("data", [])}
            for preferred in preference_list:
                if preferred.lower() in available:
                    return preferred
    except Exception:
        pass
    # Return first preference as optimistic default (it may still work via cloud pull)
    return PROVIDERS["ollama"]["default_model"]


def get_best_vision_model() -> str:
    """Return the best locally-available Ollama vision model.

    Falls back to the first entry in OLLAMA_VISION_MODELS (optimistic) if
    none are confirmed available.
    """
    ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    try:
        import requests as _req
        resp = _req.get(f"{ollama_base}/models", timeout=3)
        if resp.status_code == 200:
            available = {m["id"].lower() for m in resp.json().get("data", [])}
            for mdl in OLLAMA_VISION_MODELS:
                if mdl.lower() in available:
                    return mdl
    except Exception:
        pass
    return OLLAMA_VISION_MODELS[0]


def _messages_have_images(messages: List[Dict]) -> bool:
    """Return True when any message content contains an image_url part."""
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


_cooldowns: Dict[str, float] = {}
def _is_rate_limited(pid): return time.time() < _cooldowns.get(pid, 0)
def _mark_rate_limited(pid):
    cd = 15 if PROVIDERS.get(pid,{}).get("keyless") else COOLDOWN_SECONDS
    _cooldowns[pid] = time.time() + cd
def _is_rl_error(exc):
    msg = str(exc).lower()
    if isinstance(exc, __import__('requests').HTTPError):
        if exc.response is not None and exc.response.status_code == 429: return True
    return any(p in msg for p in ["rate limit","rate_limit","too many requests","quota","throttl"])
def _provider_secret_name(cfg: Dict[str, Any]) -> str:
    return str(cfg.get("env_key", "") or "").strip()


def _provider_api_key(cfg: Dict[str, Any]) -> str:
    if cfg.get("keyless", False):
        return "llm7" if cfg.get("label", "").lower().startswith("llm7") else ""
    secret_name = _provider_secret_name(cfg)
    if not secret_name:
        return ""
    return str(get_secret(secret_name, "") or "").strip()


def _has_key(cfg):
    return cfg.get("keyless", False) or bool(_provider_api_key(cfg))

def _smart_order(task: str, resources: Optional[Dict[str, Any]] = None) -> List[str]:
    pref = _config["provider"]
    avail = {pid for pid,cfg in PROVIDERS.items() if _has_key(cfg) and not _is_rate_limited(pid)}
    complexity_profile = _build_complexity_profile(task)
    complexity = complexity_profile["label"]
    resource_hint = _resource_tier(resources or get_system_resources())

    if resource_hint == "constrained":
        tier_order = ["low", "medium", "high"]
        low_medium = set(PROVIDER_TIERS["low"] + PROVIDER_TIERS["medium"])
        avail = {pid for pid in avail if pid in low_medium}
    elif resource_hint == "low":
        tier_order = ["low", "medium", "high"]
    else:
        tier_order = ["high","medium","low"] if complexity=="high" else \
                     ["medium","low","high"] if complexity=="medium" else ["low","medium","high"]

    ordered: List[str] = []
    for tier in tier_order:
        for pid in PROVIDER_TIERS[tier]:
            if pid in avail and pid not in ordered: ordered.append(pid)
    for pid in PROVIDERS:
        if pid in avail and pid not in ordered: ordered.append(pid)
    if pref != "auto" and pref in ordered:
        ordered.remove(pref); ordered.insert(0, pref)

    # Persona-level provider priority override (when provider=auto).
    if pref == "auto":
        persona_name = get_active_persona_name()
        persona_override = get_provider_persona_override(persona_name)
        if persona_override:
            boosted = [p for p in persona_override if p in ordered]
            ordered = boosted + [p for p in ordered if p not in boosted]

    # Hardware-aware bias: promote providers that can exploit local/accelerated compute.
    try:
        from .hardware import get_hardware_routing_hint

        hw = get_hardware_routing_hint()
        if hw.get("has_gpu"):
            gpu_favored = {"ollama", "groq", "cerebras", "nvidia", "github_models"}
            gpu_first = [p for p in ordered if p in gpu_favored]
            cpu_rest = [p for p in ordered if p not in gpu_favored]
            ordered = gpu_first + cpu_rest
        elif hw.get("prefer_local") and "ollama" in ordered:
            ordered = ["ollama"] + [p for p in ordered if p != "ollama"]
    except Exception:
        pass

    # Budget-aware filtering: drop providers that exceed the cost ceiling
    if BUDGET_TIER != "any":
        max_cost = _BUDGET_MAX_COST.get(BUDGET_TIER, 999.0)
        affordable = [pid for pid in ordered if _PROVIDER_COST_PER_1K_TOKENS.get(pid, 0.0) <= max_cost]
        if affordable:
            ordered = affordable

    # Mixture-of-Experts: boost specialist providers to front when task type detected
    if pref == "auto" and resource_hint != "constrained":
        spec = complexity_profile.get("specialization")
        if not spec and complexity_profile.get("score", 0) >= 5:
            spec = "reasoning"
        if spec:
            preferred = [pid for pid in PROVIDER_SPECIALIZATIONS[spec] if pid in avail]
            rest = [pid for pid in ordered if pid not in preferred]
            ordered = preferred + rest

    # Auto-select best local Ollama model for the detected task type
    if pref == "auto" and "ollama" in avail:
        spec = complexity_profile.get("specialization")
        if not spec and complexity_profile.get("label") == "high":
            spec = "reasoning"
        # Map from MoE specialization names to OLLAMA_MODEL_PREFERENCES keys
        _type_map = {"coding": "coding", "research": "research",
                     "creative": "creative", "reasoning": "reasoning"}
        otype = _type_map.get(spec or "", "general")
        best_model = get_best_ollama_model(otype)
        # Temporarily override Ollama default_model for this call cycle
        PROVIDERS["ollama"]["_selected_model"] = best_model

    return ordered


def _smart_order_for_vision(messages: List[Dict]) -> None:
    """If *messages* contain image_url parts and Ollama is available,
    override the Ollama selected model to the best vision model.

    Call this right before the provider loop in call_llm_with_fallback.
    """
    if not _messages_have_images(messages):
        return
    ollama_cfg = PROVIDERS.get("ollama")
    if ollama_cfg and (_has_key(ollama_cfg)) and not _is_rate_limited("ollama"):
        ollama_cfg["_vision_override"] = get_best_vision_model()

# ── personas ──────────────────────────────────────────────────────────────────
PERSONAS: Dict[str, Dict] = {
    "general": {
        "label": "General",
        "emoji": "⚡",
        "description": "Balanced assistant for any task",
        "temperature": 0.2,
        "system_extra": "",
    },
    "coder": {
        "label": "Coder",
        "emoji": "💻",
        "description": "Focused on writing, reviewing and shipping code",
        "temperature": 0.1,
        "system_extra": (
            "You are in CODER mode. Prioritise: write_file, run_command, read_file, commit_push. "
            "Always write complete, production-quality code. Add error handling and comments. "
            "Prefer plan → write files → run tests → commit. Never leave TODOs without implementing them."
        ),
    },
    "researcher": {
        "label": "Researcher",
        "emoji": "🔬",
        "description": "Deep dives, web research and structured summaries",
        "temperature": 0.3,
        "system_extra": (
            "You are in RESEARCHER mode. Prioritise: web_search, respond with citations. "
            "Do multiple searches to cross-reference. Structure responses with headers, "
            "bullet points, and sources. Be thorough — search at least 3 angles before concluding. "
            "Always note confidence level and limitations of the information found.",
        )
    },
    "creative": {
        "label": "Creative",
        "emoji": "🎨",
        "description": "Writing, brainstorming, image prompts and ideas",
        "temperature": 0.8,
        "system_extra": (
            "You are in CREATIVE mode. Be imaginative, expressive and original. "
            "For writing tasks: vary sentence length, use vivid language, show don't tell. "
            "For image generation: craft rich detailed prompts (style, lighting, mood, composition). "
            "Use image_gen to visualise ideas. Suggest unexpected angles and perspectives."
        ),
    },
    "architect": {
        "label": "Nexus Prime Cloud",
        "emoji": "🔷",
        "description": "Lead architect of the full Nexus Systems Ecosystem",
        "temperature": 0.05,
        "system_extra": (
            "You are the Nexus Prime Cloud — lead architect of the Nexus Systems Ecosystem (80 tools). "
            "Think like a visionary systems engineer: architecture first, then execution. "
            "Always reference Tool #XX from the Nexus blueprint (github.com/The-No-Hands-company/Nexus). "
            "Champion sovereignty, zero lock-in, privacy-first, and federated principles. "
            "When building: start with clean architecture, modular design, self-hosted-first. "
            "Use nexus_status to check the current state of the Nexus ecosystem at the start of every task. "
            "Suggest how new work connects to existing tools and where it fits in the ecosystem."
        ),
    },
}

def get_active_persona() -> Dict:
    return PERSONAS.get(_config["persona"], PERSONAS["general"])

def get_system_prompt() -> str:
    """Build the system prompt for the current persona."""
    persona = get_active_persona()
    extra = persona["system_extra"]
    base = TOOLS_DESCRIPTION
    if extra:
        base = base.rstrip() + f"\n\nPersona instructions:\n{extra}\n"
    return base

# ── system prompt ─────────────────────────────────────────────────────────────
TOOLS_DESCRIPTION = """You are a sovereign Nexus AI coding agent, part of the Nexus Systems Ecosystem (https://github.com/The-No-Hands-company/Nexus).

Reply ONLY with valid JSON — no markdown fences, no extra text.

Available actions:

  { "action": "clarify",    "questions": [{"id":"q1","text":"?","options":["A","B"]}] }
  { "action": "plan",       "title": "What I'm building", "steps": ["1. ...", "2. ..."] }
  { "action": "think",      "thought": "brief reasoning" },
  { "action": "think_deep",  "query": "complex question", "mode": "tree" }  -- Tree-of-Thought,
  { "action": "think_deep",  "query": "complex question", "mode": "graph" }  -- Graph-of-Thought
  { "action": "think_deep",  "query": "complex question", "mode": "tree" }  ← Tree-of-Thought reasoning
  { "action": "respond",    "content": "<markdown>", "confidence": 0.95 }
  { "action": "get_time",   "timezone": "Europe/Stockholm" }
  { "action": "web_search", "query": "search terms" }
  { "action": "image_gen",  "prompt": "a cyberpunk city at night, neon lights, rain", "width": 512, "height": 512 }
  { "action": "calculate",  "expr": "2 ** 32 / 1024" }
  { "action": "weather",    "location": "Stockholm" }
  { "action": "currency",   "amount": 100, "from": "USD", "to": "SEK" }
  { "action": "convert",    "value": 5.5, "from_unit": "km", "to_unit": "miles" }
  { "action": "regex",      "pattern": "\\d+", "text": "abc 123", "flags": "i" }
  { "action": "base64",     "text": "hello", "mode": "encode" }
  { "action": "json_format","text": "{\"a\":1}" }
  { "action": "generate_image","prompt": "a glowing neon city at night","width": 1024,"height": 1024 }
  { "action": "nexus_status" },
  { "action": "ollama_list_models" }  -- list all locally available Ollama models
  { "action": "mcp_call",    "name": "github_issues", "args": {} }
  { "action": "generate_image",  "prompt": "a glowing neon city at night","width": 512,"height": 512 }
  { "action": "youtube_transcript","url": "https://youtube.com/watch?v=..." }
  { "action": "read_pdf",   "path": "document.pdf" }
  { "action": "read_docx",  "path": "report.docx" }
  { "action": "read_xlsx",  "path": "data.xlsx" }
  { "action": "read_pptx",  "path": "slides.pptx" }
  { "action": "diff",       "original": "old text", "modified": "new text", "filename": "app.py" }
  { "action": "query_db",   "connection_string": "sqlite:///data.db", "query": "SELECT * FROM table LIMIT 10" }
  { "action": "inspect_db", "connection_string": "sqlite:///data.db" }  ← list all tables, columns and row counts
    { "action": "cron_schedule", "name": "nightly-backup", "task": "Export all chats to markdown", "schedule": "1d" }
    { "action": "cron_list" }    ← list active background jobs
    { "action": "cron_cancel", "job_id": "abc12345" }
  { "action": "kg_store",  "name": "entity name", "entity_type": "person|project|concept", "facts": {"key": "value"}, "relations": [{"relation": "works_on", "to": "other entity"}] }  ← save to long-term knowledge graph
  { "action": "kg_query",  "query": "search terms", "limit": 10 }  ← search knowledge graph
  { "action": "kg_list",   "entity_type": "person" }  ← list all KG entities (optionally by type)
  { "action": "read_csv",   "path": "data.csv" }
  { "action": "write_csv",  "path": "output.csv", "data": [["col1","col2"],["a","b"]] }
  { "action": "api_call",   "method": "GET", "url": "https://api.example.com/data", "headers": {}, "body": null }
  { "action": "read_page",  "url": "https://example.com" }
  { "action": "sub_agent",  "task": "focused subtask description", "context": "relevant context" }
  { "action": "orchestrate_goal", "goal": "Build a REST API with user auth", "strategy": "parallel", "max_subtasks": 6 }
  { "action": "decompose_goal", "goal": "Build a REST API with user auth", "max_subtasks": 6 }
  { "action": "select_model", "task": "Refactor the authentication flow", "prefer_quality": true }
  { "action": "write_file", "path": "src/app.py", "content": "..." }  ← ensure content is valid JSON string (escape quotes, newlines)
  { "action": "read_file",  "path": "README.md" }
  { "action": "list_files", "pattern": "**/*.py" }
  { "action": "delete_file","path": "old.txt" }
  { "action": "run_command","cmd": "pip install flask" }
    { "action": "run_command","cmd": "pip install flask", "approval_id": "appr_xxx" }  -- optional for HITL approval mode
    { "action": "clone_repo",   "url": "https://github.com/user/repo", "dest_path": "/absolute/or/relative/path" }
  { "action": "create_repo",  "name": "my-project", "description": "...", "private": false, "org": "" }
  { "action": "commit_push","message": "feat: ...", "repo_url": "https://github.com/user/repo" }
  { "action": "youtube",      "url": "https://youtube.com/watch?v=..." }
  { "action": "read_pdf",     "path": "document.pdf" }
  { "action": "read_docx",    "path": "report.docx" }
  { "action": "read_xlsx",    "path": "data.xlsx" }
  { "action": "read_pptx",    "path": "slides.pptx" }
  { "action": "diff",         "original": "old text", "modified": "new text", "filename": "app.py" }
  { "action": "simulate",     "topic": "Will interest rates drop in 2026?", "seed": "optional context", "n_personas": 5, "n_rounds": 3 }  ← swarm prediction via persona debate
  { "action": "agent_message", "from": "planner", "to": "architect", "content": "Proceed with module split." }  ← agent-to-agent message

Rules:
- clarify ONLY for new project creation where architecture choices matter. 2-4 questions max.
- plan BEFORE building 3+ files. Then execute immediately.
- clone_repo: use the exact URL from the user's message. Never use placeholder URLs.
- commit_push: always include repo_url so the right repo gets pushed.
- run_command: no rm -rf, sudo, or destructive ops.
- get_time for any time/date question — never web_search for this.
- calculate/weather/currency/convert for math, weather, money, units.
- image_gen for any request to generate, draw, create, or visualise an image.
- write_file produces artifacts if it's HTML/SVG/CSS+JS — the UI will render them.
- Never ask for info you can get with tools.
"""

# ── tool executors ────────────────────────────────────────────────────────────
import requests as _req

def _time_re() -> str:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        return ""
    except: return ""

def tool_get_time(timezone: str = "UTC") -> str:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        ALIASES = {"sweden":"Europe/Stockholm","stockholm":"Europe/Stockholm",
            "uk":"Europe/London","london":"Europe/London",
            "new york":"America/New_York","nyc":"America/New_York",
            "los angeles":"America/Los_Angeles","la":"America/Los_Angeles",
            "tokyo":"Asia/Tokyo","japan":"Asia/Tokyo","paris":"Europe/Paris",
            "france":"Europe/Paris","berlin":"Europe/Berlin","germany":"Europe/Berlin",
            "dubai":"Asia/Dubai","uae":"Asia/Dubai","sydney":"Australia/Sydney",
            "australia":"Australia/Sydney","jakarta":"Asia/Jakarta","indonesia":"Asia/Jakarta",
            "utc":"UTC","gmt":"GMT"}
        tz_name = ALIASES.get(timezone.lower().strip(), timezone)
        try: tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError: return f"Unknown timezone: '{timezone}'"
        now = datetime.now(tz)
        return now.strftime("**%H:%M:%S** %Z — %A, %B %d %Y (UTC%z)")
    except Exception as e: return f"Time lookup failed: {e}"

def tool_web_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=6))
        if not results: return "No results found."
        # Return structured JSON so the agent can cite sources
        import json as _json
        sources = [{"title": r["title"], "url": r["href"],
                    "snippet": r["body"][:300], "domain": r["href"].split("/")[2] if "://" in r["href"] else ""}
                   for r in results]
        lines = [f"[{i+1}] **{s['title']}** ({s['domain']})\n{s['url']}\n{s['snippet']}"
                 for i, s in enumerate(sources)]
        structured = "\n\n".join(lines)
        structured += f"\n\n[SOURCES_JSON]{_json.dumps(sources)}[/SOURCES_JSON]"
        return structured
    except Exception as e: return f"Search failed: {e}"

def tool_image_gen(prompt: str, width: int = 512, height: int = 512) -> str:
    """Generate image via Pollinations.ai — completely free, no API key."""
    import urllib.parse
    w = min(max(int(width), 256), 1024)
    h = min(max(int(height), 256), 1024)
    encoded = urllib.parse.quote(prompt)
    # Pollinations returns a direct image URL
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&nologo=true"
    return f"![Generated image]({url})\n\n*Prompt: {prompt}*"

def tool_mcp_call(name: str, args: dict) -> str:
    """Call an external MCP tool by name."""
    if not _MCP_TOOLS:
        return 'MCP tools not configured. Set MCP_TOOLS env var as a JSON array.'
    for t in _MCP_TOOLS:
        if t["name"] == name:
            try:
                import requests as _r
                url = t["url"]
                headers = t.get("headers", {})
                resp = _r.get(url, headers=headers, timeout=15)
                status_text = resp.text[:2000]
                return f'Status: {resp.status_code}\n\n{status_text}'
            except Exception as e:
                return f'MCP call failed: {e}'
    return f'MCP tool not found: {name}. Available: {[t["name"] for t in _MCP_TOOLS]}'


def tool_ollama_list_models() -> str:
    import requests as _r
    try:
        resp = _r.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            if not models:
                return "No Ollama models found. Run: ollama pull glm-5.1:cloud"
            lines = ["Available Ollama models:"]
            for m in models:
                name = m.get("name","?")
                sz = m.get("size",0)
                gb = sz/(1024**3) if sz else 0
                lines.append("  - " + name + (" (%.1fGB)" % gb if gb else ""))
            lines.append("")
            lines.append("Suggested for coding: codellama, qwen2.5-coder")
            lines.append("Suggested for reasoning: glm-5.1:cloud, deepseek-r1")
            return "\n".join(lines)
        return "Ollama not responding at localhost:11434"
    except Exception as e:
        return "Could not connect to Ollama: " + str(e) + "\nMake sure Ollama is running: ollama serve"


def tool_nexus_status() -> str:
    """Fetch the Nexus repo to report ecosystem status — called by the architect persona."""
    import requests as _r
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        resp = _r.get("https://api.github.com/repos/The-No-Hands-company/Nexus", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            desc = data.get("description", "No description")
            lang = data.get("language", "—")
            stars = data.get("stargazers_count", 0)
            return (f"🔷 Nexus Systems Ecosystem Status\n"
                    f"Description: {desc}\nLanguage: {lang} | ⭐ {stars}\n"
                    f"URL: https://github.com/The-No-Hands-company/Nexus\n"
                    f"Status: Active — 80 tools across verticals")
        return "⚠️ Could not reach Nexus repo."
    except Exception as e:
        return f"⚠️ nexus_status failed: {e}"

def tool_write_file(path: str, content: str, workdir: str) -> str:
    full = os.path.join(workdir, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f: f.write(content)
    return f"Wrote {path} ({len(content)} chars)"

def tool_read_file(path: str, workdir: str) -> str:
    full = os.path.join(workdir, path)
    if not os.path.exists(full): return f"File not found: {path}"
    with open(full, "r", encoding="utf-8", errors="replace") as f: content = f.read()
    lines = content.splitlines()
    preview = "\n".join(lines[:300])
    suffix = f"\n... ({len(lines)-300} more lines)" if len(lines)>300 else ""
    return f"```\n{preview}{suffix}\n```"

def tool_list_files(pattern: str, workdir: str) -> str:
    matches = glob.glob(os.path.join(workdir, pattern), recursive=True)
    rel = [os.path.relpath(m, workdir) for m in sorted(matches) if os.path.isfile(m)]
    return "\n".join(rel) if rel else "(no files found)"

def tool_delete_file(path: str, workdir: str) -> str:
    full = os.path.join(workdir, path)
    if not os.path.exists(full): return f"Not found: {path}"
    os.remove(full); return f"Deleted {path}"

def tool_run_command(cmd: str, workdir: str) -> str:
    BLOCKED = ["rm -rf /","sudo","ncat","mkfs","dd if=",":(){ :|:& };:",
               "cd /app",">/app",">> /app","/app/main.py","/app/agent.py"]
    for b in BLOCKED:
        if b in cmd: return f"❌ Blocked: {cmd}"
    # Common sandbox mismatch: host mount paths are not visible in this runtime.
    if ("/run/media/" in cmd or "/media/" in cmd) and not (os.path.exists("/run/media") or os.path.exists("/media")):
        return ("❌ Host mount paths are not available in this runtime. "
                f"Use a path under the current workspace: {workdir}")
    try:
        # Resource limits: 256MB RAM, 10s CPU
        def _preexec():
            try:
                resource.setrlimit(resource.RLIMIT_AS,  (268435456, 268435456))
                resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
            except Exception: pass

        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=workdir, timeout=60, preexec_fn=_preexec)
        out = (r.stdout + r.stderr).strip()
        return out[:4000] if out else "(no output)"
    except subprocess.TimeoutExpired: return "⏱ Command timed out after 60s"
    except Exception as e: return f"Error: {e}"

def tool_clone_repo(url: str, token: str, workdir: str, dest_path: str = "") -> str:
    """
    Fetch a GitHub repo via the Contents API (plain HTTPS, no git binary needed).
    Works in sandboxes where outbound git:// / git+https is blocked.
    Falls back to subprocess git clone if API fetch fails.
    """
    import requests as _req, base64 as _b64

    # Parse owner/repo from URL
    parts = url.rstrip('/').replace('.git','').split('/')
    try:
        owner, repo_name = parts[-2], parts[-1]
    except IndexError:
        return f"❌ Cannot parse owner/repo from URL: {url}"

    if dest_path:
        dest = dest_path if os.path.isabs(dest_path) else os.path.join(workdir, dest_path)
    else:
        dest = os.path.join(workdir, repo_name)

    dest = os.path.abspath(dest)
    parent = os.path.dirname(dest)
    try:
        os.makedirs(parent, exist_ok=True)
    except Exception as e:
        return f"❌ Destination path is not writable: {parent} ({e})"

    if os.path.exists(dest) and os.listdir(dest):
        top = [f for f in os.listdir(dest) if not f.startswith('.')][:20]
        return f"Already fetched at {dest}\nFiles: {', '.join(top)}"

    os.makedirs(dest, exist_ok=True)
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _fetch_tree(owner, repo, path="", depth=0):
        """Recursively fetch directory contents via API."""
        if depth > 4:
            return 0   # safety limit
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        try:
            resp = _req.get(api_url, headers=headers, timeout=20)
            if resp.status_code == 404:
                return 0
            resp.raise_for_status()
        except Exception as e:
            return 0

        items = resp.json()
        if isinstance(items, dict):
            items = [items]   # single file returned

        fetched = 0
        for item in items:
            item_path = item.get("path", "")
            local_path = os.path.join(dest, item_path)

            if item["type"] == "dir":
                os.makedirs(local_path, exist_ok=True)
                fetched += _fetch_tree(owner, repo, item_path, depth+1)
            elif item["type"] == "file":
                # Skip very large files (>500KB)
                if item.get("size", 0) > 500_000:
                    continue
                try:
                    file_resp = _req.get(item["url"], headers=headers, timeout=20)
                    file_resp.raise_for_status()
                    content = file_resp.json().get("content", "")
                    decoded = _b64.b64decode(content)
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(decoded)
                    fetched += 1
                except Exception:
                    pass
        return fetched

    # Try API fetch first
    count = _fetch_tree(owner, repo_name)

    if count == 0:
        # API failed — fall back to git subprocess
        auth_url = url
        if token:
            auth_url = url.replace("https://", f"https://{token}@")
        r = subprocess.run(
            ["git", "clone", "--depth=1", auth_url, dest],
            capture_output=True, text=True, timeout=90,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        )
        if r.returncode != 0:
            return (f"❌ Both API fetch and git clone failed.\n"
                    f"API: fetched 0 files. Git: {(r.stdout+r.stderr).strip()[:300]}")
        count = sum(len(fs) for _,_,fs in os.walk(dest))

    top = sorted([f for f in os.listdir(dest) if not f.startswith('.')])[:20]
    return (f"✅ Fetched {owner}/{repo_name} via GitHub API ({count} files)\n"
            f"Local path: {dest}\n"
            f"Top-level: {', '.join(top)}")

def tool_create_repo(name: str, description: str, private: bool,
                     token: str, org: str = "") -> str:
    """Create a new GitHub repo via API and return its clone URL."""
    import requests as _r
    if not token:
        return "❌ No GitHub token — cannot create repo."
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "name":        name,
        "description": description,
        "private":     private,
        "auto_init":   True,   # creates main branch with README
    }
    url = f"https://api.github.com/orgs/{org}/repos" if org else "https://api.github.com/user/repos"
    try:
        resp = _r.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data      = resp.json()
        clone_url = data["clone_url"]
        html_url  = data["html_url"]
        return f"✅ Created repo: {html_url}\nClone URL: {clone_url}"
    except Exception as e:
        try:
            err = resp.json().get("message","")
        except Exception:
            err = str(e)
        return f"❌ Repo creation failed: {err}"


def tool_commit_push(message: str, repo_url: str, token: str, workdir: str) -> str:
    # Safety: never push to an empty/default repo URL — require explicit target
    if not repo_url:
        return ("❌ commit_push blocked: no repo_url specified. "
                "Always include 'repo_url' pointing to the target repository.")
    # Prevent pushing to the Nexus AI repo from an external task
    protected = ["The-No-Hands-company/Claude-alt", "claude-alt",
                 "The-No-Hands-company/Nexus-AI", "Nexus-AI"]
    if any(p.lower() in repo_url.lower() for p in protected):
        return ("❌ commit_push blocked: cannot push to the Nexus AI repo from an external task. "
                "Use a different target repository.")
    repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git','')
    repo_dir = os.path.join(workdir, repo_name) if repo_name and os.path.isdir(os.path.join(workdir, repo_name)) else workdir

    import requests as _req, base64 as _b64, hashlib as _hl

    # Parse owner/repo
    parts = repo_url.rstrip('/').replace('.git','').split('/')
    try:
        owner, repo_name_api = parts[-2], parts[-1]
    except IndexError:
        return f"❌ Cannot parse owner/repo from URL: {repo_url}"

    gh_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def _get_sha(path_in_repo):
        """Get the SHA of an existing file (needed for updates)."""
        r = _req.get(
            f"https://api.github.com/repos/{owner}/{repo_name_api}/contents/{path_in_repo}",
            headers=gh_headers, timeout=15
        )
        if r.status_code == 200:
            return r.json().get("sha")
        return None

    def _push_file(local_path, repo_path):
        """Push a single file via GitHub Contents API."""
        with open(local_path, "rb") as f:
            raw = f.read()
        encoded = _b64.b64encode(raw).decode()
        sha = _get_sha(repo_path)
        payload = {"message": message, "content": encoded}
        if sha:
            payload["sha"] = sha
        r = _req.put(
            f"https://api.github.com/repos/{owner}/{repo_name_api}/contents/{repo_path}",
            headers=gh_headers, json=payload, timeout=20
        )
        return r.status_code in (200, 201)

    # Walk repo_dir and push all non-.git files
    pushed, failed = 0, 0
    SKIP_DIRS  = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', '.next'}
    SKIP_EXTS  = {'.pyc', '.pyo', '.class', '.o', '.so', '.dll', '.exe', '.bin'}
    MAX_SIZE   = 900_000  # GitHub API limit is 1MB, stay under

    for dirpath, dirnames, filenames in os.walk(repo_dir):
        # Prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SKIP_EXTS:
                continue
            local_abs  = os.path.join(dirpath, fname)
            if os.path.getsize(local_abs) > MAX_SIZE:
                continue
            repo_rel = os.path.relpath(local_abs, repo_dir).replace(os.sep, '/')
            if _push_file(local_abs, repo_rel):
                pushed += 1
            else:
                failed += 1

    if pushed == 0 and failed == 0:
        return "Nothing to push (no files found)."
    if pushed == 0:
        return f"❌ Push failed for all {failed} files. Check token permissions."
    return (f"✅ Pushed {pushed} file(s) to {owner}/{repo_name_api}\n"
            f"Commit message: {message}"
            + (f"\n⚠️ {failed} file(s) failed to push." if failed else ""))

# ── artifact detection ────────────────────────────────────────────────────────
_ARTIFACT_EXTS = {'.html','htmlv','.svg','.jsx','.tsx'}
def _is_artifact(path: str, content: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext in _ARTIFACT_EXTS: return True
    if ext in ('.js','.ts') and ('<div' in content or 'React' in content): return True
    return False

# ── direct intent handlers ────────────────────────────────────────────────────
_TIME_RE2 = re.compile(
    r'\b(what(?:\'s| is)(?: the)? (?:current )?time(?: in| at)?|'
    r'current time(?: in)?|time(?: right)? now(?: in)?|what time(?: is it)?)\b',re.IGNORECASE)
_DATE_RE2 = re.compile(
    r'\b(what(?:\'s| is)(?: the)? (?:current |today\'?s? )?date|today\'?s? date|what day is)\b',re.IGNORECASE)
_CALC_RE  = re.compile(r'^[\d\s\+\-\*\/\%\^\(\)\.e]+$')
_WEATHER_RE = re.compile(r'\bweather\b.*\bin\b|\bweather\b.*\bfor\b|\b(forecast|temperature)\b.*\bin\b',re.IGNORECASE)
_CURRENCY_RE = re.compile(r'(\d[\d,\.]*)\s*([A-Z]{3})\s+(?:to|in|→)\s*([A-Z]{3})',re.IGNORECASE)
_CONVERT_RE = re.compile(r'(\d[\d,\.]*)\s*([\w]+)\s+(?:to|in|→)\s*([\w]+)',re.IGNORECASE)

def _try_direct(task: str) -> Optional[str]:
    if _TIME_RE2.search(task):
        loc = re.search(r'\b(?:in|at|for)\s+([A-Za-z][A-Za-z\s/]{1,30})\??$',task,re.IGNORECASE)
        return tool_get_time(loc.group(1).strip() if loc else "UTC")
    if _DATE_RE2.search(task):
        return tool_get_time("UTC")
    m = _CURRENCY_RE.search(task)
    if m:
        from .tools_builtin import tool_currency
        return tool_currency(float(m.group(1).replace(',','')), m.group(2), m.group(3))
    return None

# ── LLM callers ───────────────────────────────────────────────────────────────
def _parse_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if not raw: raise ValueError("Empty response")
    if raw.startswith("```"):
        parts = raw.split("```"); raw = parts[1].strip()
        if raw.lower().startswith("json"): raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Try to salvage write_file actions with broken content fields
        # by extracting action + path and using raw content between first/last quote pairs
        if '"action": "write_file"' in raw or '"action":"write_file"' in raw:
            try:
                # Extract path
                import re as _re
                path_m = _re.search(r'"path"\s*:\s*"([^"]+)"', raw)
                # Extract content as everything between first "content": " and last "
                cont_m = _re.search(r'"content"\s*:\s*"(.*)"', raw, _re.DOTALL)
                if path_m and cont_m:
                    content = cont_m.group(1)
                    # Basic unescape
                    content = content.replace("\\n","\n").replace("\\t","\t").replace('\\"',"\"")
                    return {"action":"write_file","path":path_m.group(1),"content":content}
            except Exception:
                pass
        # Fall back to treating as plain text response
        return {"action": "respond", "content": raw}

def _is_bad_output(action: Dict[str, Any]) -> bool:
    """Detect clearly malformed or useless responses worth retrying."""
    kind    = action.get("action","")
    content = action.get("content","").strip()
    # Empty respond
    if kind == "respond" and not content:
        return True
    # Responded with a placeholder URL
    if kind in ("clone_repo","run_command") and "username/repo" in str(action):
        return True
    return False

# ── typed tool retry ──────────────────────────────────────────────────────────
_RETRY_TOOL_KINDS: set = {
    "web_search", "read_page", "api_call",
    "youtube_transcript", "youtube",
}

def _classify_tool_error(exc: Exception) -> str:
    """Classify an exception from a tool call into a retry category."""
    msg = str(exc).lower()
    if any(p in msg for p in ("rate limit", "rate_limit", "429", "too many requests", "quota")):
        return "rate_limit"
    if any(p in msg for p in ("timed out", "timeout", "read timeout", "connect timeout")):
        return "timeout"
    if any(p in msg for p in ("connection error", "connectionerror", "name or service", "network unreachable")):
        return "connection"
    return "other"

_RETRY_DELAYS: Dict[str, float] = {
    "rate_limit": 20.0,
    "timeout":     5.0,
    "connection":  3.0,
    "other":       0.0,   # no retry
}


def _persist_conversation_memory(messages: List[Dict], sid: str = "", persona: Optional[str] = None) -> bool:
    try:
        summary = _summarize_history(messages, call_llm_with_fallback)
        if not summary:
            return False
        add_memory(summary, tags=[sid or "anon"], persona=persona or get_active_persona_name())
        return True
    except Exception:
        return False

def _build_content(text: str, files: List[Dict]) -> Any:
    if not files: return text
    parts: List[Dict] = []
    text_files = []
    for f in files:
        if f.get("type","").startswith("image/"):
            parts.append({"type":"image_url","image_url":{"url":f"data:{f['type']};base64,{f['content']}"}})
        else:
            text_files.append(f"[File: {f['name']}]\n{f['content']}")
    full = ("\n\n".join(text_files)+"\n\n"+text).strip() if text_files else text
    parts.append({"type":"text","text":full})
    return parts


def _estimate_tokens(text: str) -> int:
    """Rough BPE estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _messages_token_estimate(messages: List[Dict]) -> int:
    total = 0
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str):
            total += _estimate_tokens(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict):
                    total += _estimate_tokens(part.get("text", ""))
    return total


def _ollama_pull(model: str, base_url: str) -> None:
    """Auto-pull a missing Ollama model (pull-on-demand)."""
    import requests as _req
    ollama_base = base_url.rstrip("/")
    if ollama_base.endswith("/v1"):
        ollama_base = ollama_base[:-3]
    print(f"🔄 Ollama pull-on-demand: {model}")
    try:
        r = _req.post(f"{ollama_base}/api/pull", json={"name": model, "stream": False}, timeout=600)
        r.raise_for_status()
        print(f"✅ Pulled {model}")
    except Exception as exc:
        print(f"⚠️ Could not pull {model}: {exc}")
        raise


def _call_openai(cfg: Dict, messages: List[Dict]) -> Dict[str, Any]:
    import requests
    secret_name = _provider_secret_name(cfg)
    ctx = inject_request_credentials([secret_name]) if secret_name else nullcontext({})
    with ctx as creds:
        api_key = str((creds.get(secret_name) if secret_name else "") or _provider_api_key(cfg) or "")
    model = _config["model"] or cfg.get("_selected_model") or cfg["default_model"]
    is_local = cfg.get("local") and cfg.get("keyless")

    def _do_request():
        r = requests.post(
            cfg["base_url"].rstrip("/")+"/chat/completions",
            headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
            json={"model": model,
                  "messages":[{"role":"system","content":get_system_prompt()}]+messages,
                  "temperature":_config["temperature"],"max_tokens":4096},
            timeout=90)
        r.raise_for_status()
        return r

    try:
        resp = _do_request()
    except Exception as exc:
        if is_local and ("404" in str(exc) or "not found" in str(exc).lower()):
            _ollama_pull(model, cfg["base_url"])
            resp = _do_request()
        else:
            raise

    data = resp.json()
    msg_obj = data["choices"][0]["message"]
    content = msg_obj.get("content") or ""

    # DeepSeek reasoning_content normalization
    reasoning = msg_obj.get("reasoning_content") or ""
    result = _parse_json(content)
    if reasoning and isinstance(result, dict) and not result.get("thought"):
        result["thought"] = reasoning

    # Gemini parallel function-call ID mapping
    tool_calls = msg_obj.get("tool_calls") or []
    if tool_calls and isinstance(result, dict):
        result.setdefault("_tool_calls", [
            {"id": tc.get("id") or f"call_{i}", "function": tc.get("function", {})}
            for i, tc in enumerate(tool_calls)
        ])

    return result


def _call_grok(messages):
    import requests, time as _t
    secret_name = "GROK_API_KEY"
    with inject_request_credentials([secret_name]) as creds:
        grok_key = str(creds.get(secret_name) or get_secret(secret_name, "") or "")
    headers = {
        "Authorization": f"Bearer {grok_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _config["model"] or "grok-3",
        "messages": [{"role":"system","content":get_system_prompt()}]+messages,
        "temperature": _config["temperature"] or get_active_persona()["temperature"],
        "max_tokens": 4096,
    }
    resp = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=body, timeout=90)

    # Grok async deferred response normalization (202 → poll)
    if resp.status_code == 202:
        deferred = resp.json()
        request_id = deferred.get("request_id") or deferred.get("id", "")
        if request_id:
            for _ in range(60):
                _t.sleep(2)
                poll = requests.get(
                    f"https://api.x.ai/v1/deferred/chat/completions/{request_id}",
                    headers=headers, timeout=30)
                if poll.status_code == 200:
                    resp = poll
                    break
                elif poll.status_code not in (202, 404):
                    poll.raise_for_status()
            else:
                raise TimeoutError(f"Grok deferred request {request_id} timed out after 120s")
        else:
            raise RuntimeError("Grok returned 202 without request_id")

    resp.raise_for_status()
    return _parse_json(resp.json()["choices"][0]["message"]["content"])


def _call_claude_api(messages):
    import requests
    secret_name = "CLAUDE_API_KEY"
    with inject_request_credentials([secret_name]) as creds:
        claude_key = str(creds.get(secret_name) or get_secret(secret_name, "") or "")
    resp = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":claude_key,"anthropic-version":"2023-06-01","Content-Type":"application/json"},
        json={"model":_config["model"] or "claude-sonnet-4-20250514",
              "system":get_system_prompt(),"messages":messages,
              "temperature":_config["temperature"] or get_active_persona()["temperature"],"max_tokens":4096},timeout=90)
    resp.raise_for_status()
    content_blocks = resp.json().get("content", [])

    # Claude tool_use / tool_result parity lifecycle normalization
    text_parts: List[str] = []
    tool_use_blocks: List[Dict] = []
    for block in content_blocks:
        btype = block.get("type", "")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_use_blocks.append(block)

    if tool_use_blocks:
        tu = tool_use_blocks[0]
        return {
            "action": "tool_call",
            "tool": tu.get("name", ""),
            "tool_input": tu.get("input", {}),
            "tool_use_id": tu.get("id", ""),
            "thought": " ".join(text_parts).strip(),
        }

    return _parse_json(" ".join(text_parts))


def _call_single(pid: str, messages: List[Dict]) -> Dict[str, Any]:
    cfg = PROVIDERS[pid]
    if cfg["openai_compat"]: return _call_openai(cfg, messages)
    if pid == "grok":         return _call_grok(messages)
    if pid == "claude":       return _call_claude_api(messages)
    raise ValueError(f"No caller: {pid}")


class AllProvidersExhausted(Exception): pass


def _provider_exhausted_error(scope: str, tried: List[str], last_error: str = "") -> Dict[str, Any]:
    """Structured 503 payload with scope tag and per-provider cooldown info."""
    now = time.time()
    cooldowns = {
        pid: round(_cooldowns[pid] - now, 1)
        for pid in tried
        if pid in _cooldowns and _cooldowns[pid] > now
    }
    return {
        "error": {
            "type": "all_providers_exhausted",
            "code": "provider_exhausted",
            "message": f"All LLM providers failed for scope '{scope}'.",
            "scope": scope,
            "providers_tried": tried,
            "cooldowns_remaining_s": cooldowns,
            "detail": last_error,
            "retry_after_s": int(max(cooldowns.values(), default=0)) + 1,
        }
    }

def call_llm_with_fallback(messages: List[Dict], task: str = "") -> tuple[Dict, str]:
    import requests as _r
    tracer = None
    llm_counter = None
    llm_latency = None
    try:
        from .observability import get_tracer, LLM_CALLS_TOTAL, LLM_LATENCY

        tracer = get_tracer()
        llm_counter = LLM_CALLS_TOTAL
        llm_latency = LLM_LATENCY
    except Exception:
        tracer = None

    resources = get_system_resources()
    order = _smart_order(task or (messages[-1].get("content","") if messages else ""), resources)
    if not order: raise AllProvidersExhausted("No providers available.")
    complexity = _score_complexity(task or "")
    resource_hint = _resource_tier(resources)
    avail_ram = resources.get("available_ram_gb")
    ram_txt = f"{avail_ram}GB" if avail_ram is not None else "unknown"
    print(f"🧠 {complexity}/{resource_hint} (ram={ram_txt}) → {' → '.join(order[:4])}")
    last_err = None
    for pid in order:
        if _is_rate_limited(pid): continue
        started = time.time()
        try:
            if tracer:
                with tracer.start_as_current_span("llm.provider.call") as span:
                    if hasattr(span, "set_attribute"):
                        span.set_attribute("llm.provider", pid)
                        span.set_attribute("llm.task", task or "")
                        span.set_attribute("llm.routed_order", " -> ".join(order[:5]))
                    result = _call_single(pid, messages)
            else:
                result = _call_single(pid, messages)
            elapsed = max(0.0, time.time() - started)
            if llm_counter is not None:
                llm_counter.labels(provider=pid, status="ok").inc()
            if llm_latency is not None:
                llm_latency.labels(provider=pid).observe(elapsed)
            return result, pid
        except Exception as e:
            last_err = e
            elapsed = max(0.0, time.time() - started)
            if llm_counter is not None:
                llm_counter.labels(provider=pid, status="error").inc()
            if llm_latency is not None:
                llm_latency.labels(provider=pid).observe(elapsed)
            if _is_rl_error(e): _mark_rate_limited(pid); print(f"↩️ {pid} rate-limited")
            elif isinstance(e, (_r.ConnectionError, _r.Timeout)): print(f"⚠️ {pid} connection error")
            else: print(f"⚠️ {pid}: {e}")
    return _graceful_degraded_response(messages, task, str(last_err))


def _graceful_degraded_response(messages: List[Dict], task: str, reason: str) -> tuple[Dict, str]:
    """Graceful degradation when all cloud providers are exhausted.

    Fallback ladder:
      1. Response cache hit for identical prompt fingerprint.
      2. Local Ollama if reachable and has at least one model.
      3. Raise AllProvidersExhausted with structured payload (never bare 503 caller-side).
    """
    # 1 — Response cache
    try:
        from .redis_state import cache_get
        import hashlib as _hl
        prompt_txt = str(messages[-1].get("content", "")) if messages else ""
        cache_key = _hl.md5(prompt_txt[:512].encode(), usedforsecurity=False).hexdigest()
        cached = cache_get(cache_key)
        if cached:
            print("⚡ Graceful degradation: serving from response cache")
            if isinstance(cached, dict):
                cached = dict(cached)
                cached["_source"] = "cache"
                return cached, "cache"
            return {"action": "respond", "content": str(cached), "_source": "cache"}, "cache"
    except Exception:
        pass

    # 2 — Local Ollama fallback
    try:
        import requests as _r
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        test = _r.get(f"{ollama_url}/api/tags", timeout=2)
        if test.status_code == 200:
            tags = test.json().get("models", [])
            if tags:
                first_model = tags[0].get("name", "llama3")
                print(f"⚡ Graceful degradation: Ollama local model {first_model}")
                cfg = {"base_url": ollama_url, "model": first_model, "openai_compat": True}
                result = _call_openai(cfg, messages)
                result["_source"] = "ollama_local"
                return result, "ollama_local"
    except Exception:
        pass

    # 3 — All fallbacks exhausted: raise structured error for caller.
    print(f"⚡ Graceful degradation failed — all fallbacks exhausted (reason={reason})")
    raise AllProvidersExhausted(f"All providers exhausted and no local fallback available. reason={reason}")


def call_llm_smart(
    messages: List[Dict],
    task: str = "",
) -> tuple[Dict, str, Dict]:
    """Route a single LLM call through ensemble mode when the task is high-risk,
    otherwise use the standard fallback chain.

    Returns:
        (result_dict, provider_id, metadata_dict)

    Metadata always contains at minimum:
        ``ensemble``   — bool, True when consensus mode was used
        ``risk_score`` — float produced by score_task_risk()
    """
    effective_task = task or (messages[-1].get("content", "") if messages else "")
    risk = score_task_risk(effective_task)
    meta: Dict[str, Any] = {"ensemble": False, "risk_score": risk}

    threshold = float(_config.get("ensemble_threshold", 0.4))
    if _config.get("ensemble_mode", True) and is_high_risk(effective_task, threshold=threshold):
        print(f"🔴 High-risk task (score={risk:.2f}) — entering ensemble mode")
        try:
            result, pid, ens_meta = call_llm_ensemble(
                messages=messages,
                task=effective_task,
                providers_fn=lambda t: _smart_order(t, get_system_resources()),
                call_single_fn=_call_single,
                is_rate_limited_fn=_is_rate_limited,
                mark_rate_limited_fn=_mark_rate_limited,
            )
            meta.update(ens_meta)
            if meta.get("ensemble"):
                return result, pid, meta
            # Ensemble fell below MIN_ENSEMBLE_SIZE — fall through to standard path.
            print("⚠️  Ensemble insufficient — falling back to standard routing")
        except Exception as exc:
            print(f"⚠️  Ensemble failed ({exc}) — falling back")

    # Standard single-provider-with-fallback path.
    result, pid = call_llm_with_fallback(messages, effective_task)
    meta["ensemble"] = False
    return result, pid, meta


def _maybe_compress_history(history: List[Dict]) -> List[Dict]:
    """Compress history using the LLM-backed summarizer for very long contexts,
    falling back to the naive truncation approach for moderate lengths."""
    if len(history) <= 20:
        return history
    # For histories long enough to warrant an LLM summary, use the smart path
    if len(history) > 40:
        try:
            return CONTEXT_WINDOW.compress_history_with_llm(history, _orchestrator_llm)
        except Exception:
            pass
    head = history[:2]
    tail = history[-14:]
    omitted = len(history) - 16
    summary_msg = {
        "role":    "user",
        "content": f"[{omitted} earlier messages omitted to save context. Continue naturally.]"
    }
    return head + [summary_msg] + tail


def _get_custom_instructions() -> str:
    try:
        return load_custom_instructions()
    except Exception:
        return ""


def _orchestrator_llm(prompt: str, task: str = "") -> str:
    result, _pid = call_llm_with_fallback([{"role":"user","content":prompt}], task)
    if isinstance(result, dict):
        return result.get("content", str(result))
    return str(result)

# ── tool icons ────────────────────────────────────────────────────────────────
TOOL_ICONS = {
    "clarify":"❓","plan":"📋","think":"💭","nexus_status":"🔷","get_time":"🕐",
    "web_search":"🔍","image_gen":"🎨","calculate":"🧮","weather":"🌤️","currency":"💱",
    "convert":"📐","regex":"🔎","base64":"🔡","json_format":"📄",
    "write_file":"📝","read_file":"📖","list_files":"📂","delete_file":"🗑️",
    "run_command":"⚙️","clone_repo":"📦","commit_push":"🚀","create_repo":"🆕",
    "query_db":"🗄️","generate_image":"🎨","youtube":"▶️","read_pdf":"📑","diff":"±",
    "read_docx":"📝","read_xlsx":"📊","read_pptx":"📽️",
    "youtube_transcript":"▶️","read_page":"🌐","api_call":"🔌","sub_agent":"🤖",
    "orchestrate_goal":"🧩","decompose_goal":"🧭","select_model":"🧠",
    "simulate":"🧬","agent_message":"📨",
    "rag_ingest":"📚","rag_query":"🔎","rag_status":"📊",
    "inspect_db":"🔬","file_diff":"±",
    "cron_schedule":"⏱️","cron_list":"📆","cron_cancel":"⏹️",
    "kg_store":"🧠","kg_query":"🔭","kg_list":"🗂️",
}

# ── long-context compression ──────────────────────────────────────────────────
CONTEXT_WINDOW = ContextWindowManager()

# Legacy helper preserved for compatibility.
MAX_HISTORY_TURNS = 20   # keep last N turns before summarising older ones

def _compress_history(history: List[Dict]) -> List[Dict]:
    """
    If history is longer than MAX_HISTORY_TURNS, summarise the oldest half
    into a single system-style message to stay within context limits.
    """
    # Count real turns (skip tool result / continue messages)
    real = [(i, m) for i, m in enumerate(history)
            if isinstance(m.get("content"), str)
            and not m["content"].startswith("Tool result:")
            and not m["content"].startswith("Continue")
            and not m["content"].startswith("[MEMORY")]
    if len(real) <= MAX_HISTORY_TURNS:
        return history

    # Summarise the first half of real turns
    cutoff_idx = real[len(real) // 2][0]
    old_turns  = history[:cutoff_idx]
    new_turns  = history[cutoff_idx:]

    lines = []
    for m in old_turns:
        role    = m.get("role", "")
        content = m.get("content", "")
        if not isinstance(content, str): continue
        if content.startswith("Tool result:") or content.startswith("Continue"): continue
        prefix = "User" if role == "user" else "Assistant"
        lines.append(f"{prefix}: {content[:200]}")

    nl = "\n"
    summary = "[EARLIER CONVERSATION SUMMARY]" + nl + nl.join(lines[-30:])
    compressed_msg = {"role": "user", "content": summary}
    follow_up      = {"role": "assistant", "content": "Understood, I have context from our earlier conversation."}
    return [compressed_msg, follow_up] + new_turns


def _dispatch_builtin_traced(action: Dict[str, Any], sid: str = "") -> Dict[str, Any] | None:
    """Dispatch a built-in tool with OpenTelemetry tracing around execution."""
    tracer = None
    try:
        from .observability import get_tracer

        tracer = get_tracer()
    except Exception:
        tracer = None

    if tracer is None:
        return dispatch_builtin(action, session_id=sid or "")

    tool_name = str(action.get("action", "unknown"))
    with tracer.start_as_current_span("tool.dispatch") as span:
        if hasattr(span, "set_attribute"):
            span.set_attribute("tool.name", tool_name)
            span.set_attribute("session.id", sid or "")
            return dispatch_builtin(action, session_id=sid or "")
        return dispatch_builtin(action, session_id=sid or "")


# ── streaming agent ───────────────────────────────────────────────────────────
def stream_agent_task(task: str, history: list, files: list | None = None,
                      stop_evt=None, sid: str = "", trace_id: str = "",
                      max_tool_calls: int = 0, max_time_s: float = 0.0,
                      budget_tokens_out: int = 0) -> Iterator[Dict[str, Any]]:
    def _stopped(): return stop_evt is not None and stop_evt.is_set()

    # Extract + store token from task; mask it before sending to LLM
    token = extract_token(task)
    if token and sid:
        set_session_token(sid, token)
        yield {"type":"system","message":"🔑 Token stored for this session (not sent to AI)"}

    workdir = get_session_dir(sid) if sid else "/tmp/ca_anon"
    os.makedirs(workdir, exist_ok=True)
    session_token = get_session_token(sid) if sid else GH_TOKEN

    # Mask tokens before LLM ever sees them
    clean_task = mask_token(task)

    # Auto warm-up keeps first-turn latency stable for new/expired sessions.
    if os.getenv("AGENT_AUTO_WARMUP", "true").lower() in ("1", "true", "yes"):
        _wk = f"{sid}:{_config.get('persona', 'general')}"
        _cached = _WARMUP_CACHE.get(_wk)
        if not _cached or (time.time() - _cached.get("ts", 0)) > _WARMUP_TTL:
            try:
                warmup_agent(sid=sid or "runtime", persona=_config.get("persona", "general"))
            except Exception:
                pass

    # Accumulated reasoning trace — populated by think/think_deep steps
    _trace_steps: List[Dict[str, Any]] = []
    _tool_attempts: Dict[str, int] = {}

    def _action_sig(a: Dict[str, Any]) -> str:
        keys = ("action", "url", "dest_path", "path", "cmd", "query", "name", "repo_url")
        return "|".join(str(a.get(k, "")) for k in keys)[:800]

    def _requested_path_from_text(text: str) -> str:
        m = re.search(r"(/(?:run/media|media|home|workspace|tmp|mnt)[^\s,;]*)", text)
        if not m:
            return ""
        p = m.group(1)
        return "" if p.startswith("http") else p

    def _blocker_reason(kind: str, result_text: str) -> str:
        txt = (result_text or "").lower()
        if not txt:
            return ""
        if "host mount paths are not available in this runtime" in txt:
            return "runtime_path_mismatch"
        if "packfile cannot be mapped" in txt or "cannot allocate memory" in txt:
            return "runtime_clone_limits"
        if kind == "clone_repo" and (
            "both api fetch and git clone failed" in txt
            or "operation timed out" in txt
            or "timed out" in txt
        ):
            return "runtime_clone_limits"
        # Reserve workstation/environment change guidance for truly unavoidable cases.
        # Do not infer this from ordinary sandbox/runtime mismatches.
        return ""

    def _single_shot_blocker_reply(reason: str) -> str:
        req_path = _requested_path_from_text(clean_task) or "(path not detected)"
        if reason == "runtime_path_mismatch":
            return (
                "I hit a runtime limitation here, so I am stopping tool retries.\n\n"
                f"- Requested host path: {req_path}\n"
                f"- This Nexus AI runtime cannot access that host mount directly.\n"
                f"- This does not mean your workstation is misconfigured.\n"
                f"- Immediate fallback: I can clone into this runtime now at {workdir}, "
                "or give you a single host command to run locally.\n\n"
                "Reply with: `runtime` or `host` and I will do exactly one path."
            )
        if reason == "runtime_clone_limits":
            return (
                "I hit a runtime limitation here, so I am stopping tool retries.\n\n"
                "- Clone failed due to runtime memory/map limits in this sandbox.\n"
                f"- Your workstation may still be fine; this is runtime-specific.\n"
                "- Immediate fallback: I can provide one exact host command for your machine, "
                "or clone a smaller mirror/test repo here to verify flow.\n\n"
                "Reply with: `host command` or `sandbox test`."
            )
        if reason == "host_env_change_required":
            return (
                "I hit a blocker that cannot be solved from inside Nexus AI alone.\n\n"
                "- At this point, the remaining path requires a change on your workstation or host environment.\n"
                "- I should only say this when there is no tool-only or runtime-only workaround left.\n\n"
                "If you want, I will give you one exact host-side fix command and nothing more."
            )
        return (
            "I hit a hard blocker in this runtime and stopped retries to avoid looping.\n"
            "Tell me whether to continue on host or sandbox and I will do one direct path."
        )

    # Checkpoint tracking
    _step_idx: int = 0
    _checkpoint_events: List[Dict[str, Any]] = []

    # Direct answer bypass
    direct = _try_direct(clean_task)
    if direct and not files:
        msgs = list(history)
        msgs.append({"role":"user","content":clean_task})
        msgs.append({"role":"assistant","content":direct})
        yield {"type":"done","content":direct,"provider":"Built-in","model":"direct","history":msgs}
        return

    # Direct clone bypass
    urls = _GITHUB_URL_RE.findall(clean_task)
    if urls and _CLONE_INTENT_RE.search(clean_task):
        _requested_dest = _requested_path_from_text(clean_task)
        for url in urls:
            yield {"type":"tool","icon":"📦","action":"clone_repo",
                   "label":url,"result":"Cloning...","file_path":None,"file_content":None}
            _dest = _requested_dest
            if _dest and not _dest.endswith(url.rstrip('/').split('/')[-1].replace('.git','')):
                _dest = os.path.join(_dest, url.rstrip('/').split('/')[-1].replace('.git',''))
            result = tool_clone_repo(url, session_token, workdir, _dest)
            # Remember this repo for the rest of the session
            if sid and "Clone failed" not in result:
                set_session_repo(sid, url)
            yield {"type":"tool","icon":"📦","action":"clone_repo",
                   "label":url,"result":result,"file_path":None,"file_content":None}
        # List files for context
        all_files = []
        for url in urls:
            rname = url.rstrip('/').split('/')[-1].replace('.git','')
            rdir  = os.path.join(workdir, rname)
            if os.path.isdir(rdir):
                all_files += [os.path.relpath(os.path.join(dp,f), workdir)
                              for dp,_,fs in os.walk(rdir) for f in fs][:50]
        file_ctx = "\n".join(all_files[:60])
        clean_task = (f"[REPOS ALREADY CLONED — do NOT call clone_repo again]\n"
                      f"Cloned to {workdir}.\nFiles:\n{file_ctx}\n\n"
                      f"Original task: {clean_task}\n\n"
                      f"Now read key files, make improvements, commit and push.")

    history_list = list(history)
    raw_tokens = sum(item.get("tokens", 0) for item in CONTEXT_WINDOW.token_breakdown(history_list))
    model_budget = CONTEXT_WINDOW.get_model_context_budget(_config.get("model") or "")
    if raw_tokens > int(model_budget * 0.85):
        yield {
            "type": "context_overflow_warning",
            "history_tokens": raw_tokens,
            "model_budget": model_budget,
            "usage_ratio": round(raw_tokens / max(1, model_budget), 4),
        }

    messages: List[Dict] = _maybe_compress_history(history_list)
    messages = CONTEXT_WINDOW.compress_to_token_budget(messages, token_budget=model_budget, reserve_tokens=4096)
    # Inject long-term knowledge graph context when relevant entities exist
    _kg_ctx = kg_to_context_string(clean_task, limit=5)
    if _kg_ctx:
        messages = [
            {"role": "user",      "content": _kg_ctx},
            {"role": "assistant", "content": "Noted — I have reviewed the relevant knowledge graph context."},
        ] + messages
    # Inject long-term memory context (semantic summaries of past conversations)
    _mem_ctx = get_memory_context()
    if _mem_ctx:
        messages = [
            {"role": "user",      "content": _mem_ctx},
            {"role": "assistant", "content": "Noted — I have context from previous conversations."},
        ] + messages
    messages.append({"role":"user","content":_build_content(clean_task, files or [])})
    yield {
        "type": "token_breakdown",
        "messages": CONTEXT_WINDOW.token_breakdown(messages),
    }
    input_token_estimate = _messages_token_estimate(messages)

    providers_used: List[str] = []
    complexity = _score_complexity(clean_task)
    yield {"type":"complexity","level":complexity}

    mcts_guidance = _auto_mcts_guidance(clean_task)
    if mcts_guidance:
        best_plan = mcts_guidance.get("best_plan", [])
        plan_text = "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(best_plan))
        messages.append({
            "role": "assistant",
            "content": (
                "Automatic MCTS planning guidance for this high-complexity task:\n"
                f"{plan_text}\n\n"
                f"Best plan score: {mcts_guidance.get('best_score', 0.0):.3f}. "
                "Use this plan as guidance, but update it if tool evidence contradicts it."
            ),
        })
        yield {
            "type": "mcts_plan",
            "plan": best_plan,
            "score": mcts_guidance.get("best_score", 0.0),
            "providers": mcts_guidance.get("providers", []),
            "complexity_profile": mcts_guidance.get("complexity_profile", {}),
        }

    # ── per-request execution budget ─────────────────────────────────────────
    _budget_start = time.time()
    _tool_call_count = 0

    for _ in range(MAX_LOOP):
        # Budget checks
        if max_time_s > 0 and (time.time() - _budget_start) > max_time_s:
            yield {"type": "budget_exceeded", "reason": "max_time_s",
                   "elapsed_s": round(time.time() - _budget_start, 1)}
            break
        if max_tool_calls > 0 and _tool_call_count >= max_tool_calls:
            yield {"type": "budget_exceeded", "reason": "max_tool_calls",
                   "tool_calls": _tool_call_count}
            break
        if _stopped():
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
            yield {"type":"done","content":"*(Stopped)*","provider":cfg.get("label","?"),
                   "model":"—","history":messages}
            return

        try:
            action, pid, _llm_meta = call_llm_smart(messages, clean_task)
            if _llm_meta.get("ensemble"):
                yield {"type": "ensemble",
                       "unanimous": _llm_meta.get("unanimous"),
                       "polled": _llm_meta.get("polled", []),
                       "action_votes": _llm_meta.get("action_votes", {}),
                       "risk_score": _llm_meta.get("risk_score", 0.0)}
        except AllProvidersExhausted as e:
            time.sleep(8)
            try:
                action, pid, _llm_meta = call_llm_smart(messages, clean_task)
            except AllProvidersExhausted:
                yield {"type":"error","message":str(e)+"\n\nAdd more API keys to avoid rate limits."}
                return

        # Auto-retry once if output is clearly bad
        if _is_bad_output(action):
            print(f"⚠️ Bad output from {pid}, retrying once…")
            try:
                action, pid, _ = call_llm_smart(messages, clean_task)
            except AllProvidersExhausted:
                pass   # give up, use original bad output

        if pid not in providers_used:
            providers_used.append(pid)
            if len(providers_used) > 1:
                yield {"type":"fallback",
                       "chain":" → ".join(PROVIDERS[p]["label"] for p in providers_used)}

        kind = action.get("action")

        if kind in ("run_command", "clone_repo"):
            _sig = _action_sig(action)
            _tool_attempts[_sig] = _tool_attempts.get(_sig, 0) + 1
            if _tool_attempts[_sig] > 2:
                blocked = (
                    "❌ Repeated tool call blocked to avoid loop. "
                    "Summarize the blocker and ask one precise follow-up question."
                )
                yield {"type":"tool", "icon":TOOL_ICONS.get(kind, "🔧"), "action":kind,
                       "label":str(action)[:120], "result":blocked,
                       "file_path":None, "file_content":None, "artifact":False}
                messages.append({"role":"assistant","content":json.dumps(action)})
                messages.append({"role":"user","content":f"Tool result:\n{blocked}\n\nContinue."})
                continue

        if kind == "clarify":
            yield {"type":"clarify","questions":action.get("questions",[])}
            # Preserve full message history — when user answers, the next
            # stream call receives this history and continues with full context
            messages.append({"role":"assistant","content":json.dumps(action)})
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
            yield {"type":"done","content":"","provider":cfg.get("label","?"),
                   "model":_config["model"] or cfg.get("default_model","?"),
                   "history":messages}   # full history returned and stored in session
            return

        if kind == "plan":
            yield {"type":"plan","title":action.get("title",""),"steps":action.get("steps",[])}
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":"Plan looks good. Start building."})
            continue


        if kind == "think_deep":
            mode = action.get("mode", "tree")
            query = action.get("query", "") or action.get("thought", "")
            if mode == "critique":
                # Self-critique an existing draft in the conversation
                last_assistant = next(
                    (m["content"] for m in reversed(messages)
                     if m.get("role") == "assistant" and isinstance(m.get("content"), str)
                     and not m["content"].startswith("{") and len(m["content"]) > 20),
                    query
                )
                crit_prompt = build_critique_prompt(last_assistant, clean_task)
                try:
                    crit_action, _ = call_llm_with_fallback(
                        [{"role": "user", "content": crit_prompt}], crit_prompt
                    )
                    crit_parsed = parse_critique_response(json.dumps(crit_action))
                    reasoning = f"**Critique:** {crit_parsed.get('critique', '')}"
                    revised = crit_parsed.get("revised", "")
                    if revised:
                        reasoning += f"\n\n**Revised:** {revised}"
                except Exception as e:
                    reasoning = f"Self-critique failed: {e}"
            else:
                if mode == "graph":
                    reasoning_prompt = build_got_prompt(query)
                else:
                    reasoning_prompt = build_tot_prompt(query, mode)
                try:
                    result_action, _, _ = call_llm_smart(
                        [{"role": "user", "content": reasoning_prompt}], reasoning_prompt
                    )
                    if mode == "graph":
                        parsed = parse_got_response(json.dumps(result_action))
                    else:
                        parsed = parse_tot_response(json.dumps(result_action))
                    reasoning = parsed.get("reasoning", str(result_action))
                except Exception as e:
                    reasoning = "Tree-of-Thought reasoning failed: " + str(e)
            yield {"type": "think", "thought": reasoning}
            _trace_steps.append({"kind": "think_deep", "mode": mode, "thought": reasoning})
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": "Continue using that reasoning."})
            continue

        if kind == "think":
            yield {"type":"think","thought":action.get("thought","")}
            _trace_steps.append({"kind": "think", "thought": action.get("thought", "")})
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":"Continue based on your reasoning."})
            continue

        if kind == "respond":
            final = action.get("content", "")
            confidence = float(action.get("confidence", 1.0) or 1.0)

            # Self-critique loop: if confidence below threshold, ask the model to
            # review and improve its own answer before returning it.
            if confidence < CRITIQUE_THRESHOLD and final and len(final) > 40:
                crit_prompt = build_critique_prompt(final, clean_task)
                try:
                    crit_action, _, _ = call_llm_smart(
                        [{"role": "user", "content": crit_prompt}], crit_prompt
                    )
                    crit_parsed = parse_critique_response(json.dumps(crit_action))
                    revised = crit_parsed.get("revised", "").strip()
                    critique_text = crit_parsed.get("critique", "")
                    if revised and len(revised) > 20:
                        yield {"type": "critique",
                               "original_confidence": confidence,
                               "critique": critique_text,
                               "revised_confidence": crit_parsed.get("confidence", confidence)}
                        final = revised
                except Exception:
                    pass  # degrade gracefully; use original answer

            messages.append({"role": "assistant", "content": final})
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
            output_tokens = _estimate_tokens(final)
            # ── Sprint E: live SSE signals ────────────────────────────────────
            yield {"type": "confidence", "value": round(confidence, 4)}
            if _trace_steps:
                yield {"type": "trace", "steps": _trace_steps}
            # ── token streaming telemetry event ───────────────────────────────
            yield {
                "type": "token",
                "in_tokens": input_token_estimate,
                "out_tokens": output_tokens,
                "total_tokens": input_token_estimate + output_tokens,
                "tool_calls": _tool_call_count,
                "elapsed_s": round(time.time() - _budget_start, 2),
            }
            yield {
                "type": "token_count",
                "in_tokens": input_token_estimate,
                "out_tokens": output_tokens,
                "total": input_token_estimate + output_tokens,
            }
            # ─────────────────────────────────────────────────────────────────
            yield {
                "type": "done",
                "content": final,
                "provider": cfg.get("label", "?"),
                "model": _config["model"] or cfg.get("default_model", "?"),
                "history": messages,
                "tokens": {
                    "input": input_token_estimate,
                    "output": output_tokens,
                    "total": input_token_estimate + output_tokens,
                },
            }
            _msgs_snapshot = list(messages)
            _persona_snap = get_active_persona_name()
            threading.Thread(
                target=_persist_conversation_memory,
                args=(_msgs_snapshot, sid, _persona_snap),
                daemon=True,
            ).start()
            return

        # Sub-agent: spawn a focused LLM call for a subtask
        if kind == "sub_agent":
            sub_task    = action.get("task", "")
            sub_context = action.get("context", "")
            sub_prompt  = f"{sub_context}\n\nTask: {sub_task}" if sub_context else sub_task
            try:
                sub_action, sub_pid = call_llm_with_fallback(
                    [{"role": "user", "content": sub_prompt}], sub_task
                )
                sub_result = sub_action.get("content", str(sub_action))
            except Exception as e:
                sub_result = f"Sub-agent failed: {e}"
            yield {"type": "tool", "icon": "🤖", "action": "sub_agent",
                   "label": sub_task[:80], "result": sub_result[:400],
                   "file_path": None, "file_content": None, "artifact": False}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": f"Sub-agent result:\n{sub_result}\n\nContinue."})
            continue

        if kind == "orchestrate_goal":
            goal        = action.get("goal", "")
            strategy    = action.get("strategy", "parallel")
            max_sub     = int(action.get("max_subtasks", 6))
            _orch_id    = f"orch_{int(time.time()*1000)}"
            output      = ""
            try:
                planner  = PlanningSystem(_orchestrator_llm)
                subtasks = planner.decompose(goal, max_sub)
                yield {
                    "type":     "plan",
                    "id":       _orch_id,
                    "status":   "done",
                    "title":    f"Plan: {goal[:80]}",
                    "steps":    [{"id": t.task_id, "description": t.description,
                                  "priority": t.priority, "dependencies": t.dependencies}
                                 for t in subtasks],
                }
                _orch       = Orchestrator(_orchestrator_llm, max_parallel=1)
                sub_results = []
                for task in subtasks:
                    _stid = f"sub_{task.task_id}_{int(time.time()*1000)}"
                    yield {
                        "type":     "subtask",
                        "id":       _stid,
                        "parent_id": _orch_id,
                        "status":   "running",
                        "label":    task.description,
                        "agent":    classify_subtask(task.description),
                        "task_id":  task.task_id,
                    }
                    sr = _orch._execute_direct(task.description)
                    sub_results.append(sr)
                    yield {
                        "type":     "subtask",
                        "id":       _stid,
                        "parent_id": _orch_id,
                        "status":   "done" if sr.success else "failed",
                        "label":    task.description,
                        "agent":    sr.agent_used,
                        "result":   sr.result[:400] if sr.result else "",
                        "error":    sr.error,
                        "task_id":  task.task_id,
                    }
                output = _orch._synthesize(goal, sub_results)
            except Exception as _oe:
                output = f"Orchestration failed: {_oe}"
            yield {"type": "tool", "id": f"tool_{_orch_id}", "parent_id": _orch_id,
                   "status": "done", "icon": "🧩", "action": "orchestrate_goal", "tool_name": "orchestrate_goal",
                   "label": goal[:120], "result": output[:600],
                   "input": action, "metadata": {"goal": goal, "strategy": strategy, "subtask_count": max_sub},
                   "file_path": None, "file_content": None, "artifact": False}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": f"Tool result:\n{output}\n\nContinue."})
            continue

        if kind == "decompose_goal":
            goal = action.get("goal", "")
            max_subtasks = int(action.get("max_subtasks", 6))
            try:
                from .autonomy import PlanningSystem
                planner = PlanningSystem(_orchestrator_llm)
                tasks = planner.decompose(goal, max_subtasks)
                output = json.dumps([{
                    "id": t.task_id,
                    "description": t.description,
                    "priority": t.priority,
                    "dependencies": t.dependencies,
                } for t in tasks], indent=2)
            except Exception as e:
                output = f"Decomposition failed: {e}"
            yield {"type": "tool", "icon": "🧭", "action": "decompose_goal",
                   "label": goal[:120], "result": output,
                   "file_path": None, "file_content": None, "artifact": False}
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": f"Tool result:\n{output}\n\nContinue."})
            continue

        # ── Parallel tool fan-out ─────────────────────────────────────────────
        if kind == "parallel_tools":
            tools_list = action.get("tools") or []
            if not tools_list:
                messages.append({"role": "assistant", "content": json.dumps(action)})
                messages.append({"role": "user", "content": "Tool result:\nNo tools provided.\n\nContinue."})
                continue

            _ptid = f"ptool_{int(time.time()*1000)}"
            yield {"type": "tool_start", "id": _ptid, "action": "parallel_tools",
                   "icon": "⚡", "label": f"Parallel fan-out ({len(tools_list)} tools)",
                   "call_ids": [f"{_ptid}_{i}" for i in range(len(tools_list))]}

            def _run_one(sub_action: Dict) -> Dict:
                _sr = _dispatch_builtin_traced(sub_action, sid=sid)
                if _sr:
                    return _sr
                return {"result": f"unknown tool: {sub_action.get('action','?')}", "status": "error"}

            with __import__("concurrent.futures").futures.ThreadPoolExecutor(
                max_workers=min(len(tools_list), 6)
            ) as pool:
                _futures = {pool.submit(_run_one, t): (i, t) for i, t in enumerate(tools_list)}
                _presults = {}
                for fut in __import__("concurrent.futures").futures.as_completed(_futures, timeout=90):
                    idx, sub_act = _futures[fut]
                    call_id = f"{_ptid}_{idx}"
                    try:
                        r = fut.result()
                        _presults[call_id] = r
                        yield {"type": "tool", "id": call_id, "parent_id": _ptid,
                               "status": r.get("status", "done"),
                               "icon": TOOL_ICONS.get(sub_act.get("action", ""), "🔧"),
                               "action": sub_act.get("action", "?"), "tool_name": sub_act.get("action", "?"),
                               "label": str(sub_act)[:120], "result": str(r.get("result", ""))[:400],
                               "input": sub_act, "metadata": r.get("metadata", {}),
                               "file_path": None, "file_content": None, "artifact": False}
                    except Exception as exc:
                        _presults[call_id] = {"result": str(exc), "status": "error"}
                        yield {"type": "tool", "id": call_id, "parent_id": _ptid,
                               "status": "error", "action": sub_act.get("action", "?"),
                               "label": str(sub_act)[:120], "result": str(exc),
                               "file_path": None, "file_content": None, "artifact": False}
                        _tool_call_count += 1

            _tool_call_count += len(tools_list)
            combined = "\n".join(
                f"[{k}] {v.get('result','')}" for k, v in sorted(_presults.items())
            )
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": f"Parallel tool results:\n{combined}\n\nContinue."})
            _step_idx += 1
            if trace_id:
                _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
            continue

        # ── Compositional (chained sequential) tool calls ─────────────────────
        if kind == "chain_tools":
            tools_list = action.get("tools") or []
            if not tools_list:
                messages.append({"role": "assistant", "content": json.dumps(action)})
                messages.append({"role": "user", "content": "Tool result:\nNo tools in chain.\n\nContinue."})
                continue

            _ctid = f"ctool_{int(time.time()*1000)}"
            yield {"type": "tool_start", "id": _ctid, "action": "chain_tools",
                   "icon": "🔗", "label": f"Chained tool calls ({len(tools_list)} steps)",
                   "call_ids": [f"{_ctid}_{i}" for i in range(len(tools_list))]}

            _prev_result = ""
            _chain_results = []
            for ci, sub_action in enumerate(tools_list):
                call_id = f"{_ctid}_{ci}"
                # Inject previous result as context in the action if it uses a template
                if _prev_result and sub_action.get("_inject_prev"):
                    sub_action = dict(sub_action)
                    for k, v in sub_action.items():
                        if isinstance(v, str) and "{prev}" in v:
                            sub_action[k] = v.replace("{prev}", _prev_result[:800])
                _cr = _dispatch_builtin_traced(sub_action, sid=sid)
                if not _cr:
                    _cr = {"result": f"unknown tool: {sub_action.get('action','?')}", "status": "error"}
                _prev_result = str(_cr.get("result", ""))
                _chain_results.append(_prev_result)
                _tool_call_count += 1
                yield {"type": "tool", "id": call_id, "parent_id": _ctid,
                       "status": _cr.get("status", "done"),
                       "icon": TOOL_ICONS.get(sub_action.get("action", ""), "🔧"),
                       "action": sub_action.get("action", "?"), "tool_name": sub_action.get("action", "?"),
                       "label": str(sub_action)[:120], "result": _prev_result[:400],
                       "input": sub_action, "metadata": _cr.get("metadata", {}),
                       "file_path": None, "file_content": None, "artifact": False}

            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user",
                              "content": f"Chain final result:\n{_prev_result[:1200]}\n\nContinue."})
            _step_idx += 1
            if trace_id:
                _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
            continue

        if kind == "simulate":
            from .simulation import SimulationEngine
            topic      = action.get("topic", "")
            seed       = action.get("seed", "")
            n_personas = max(2, min(int(action.get("n_personas", 5)), 8))
            n_rounds   = max(1, min(int(action.get("n_rounds", 3)), 5))

            def _sim_llm(msgs: List[Dict]) -> str:
                try:
                    res, _ = call_llm_with_fallback(msgs, "simulation")
                    if isinstance(res, dict):
                        if res.get("action") == "respond":
                            return res.get("content", "")
                        return json.dumps(res)
                    return str(res)
                except Exception as _se:
                    return f"error: {_se}"

            _sim_id = f"sim_{int(time.time()*1000)}"
            yield {
                "type": "tool", "id": _sim_id, "parent_id": None, "status": "running",
                "icon": "🧬", "action": "simulate", "tool_name": "simulate",
                "label": topic[:120], "result": "", "input": action,
                "metadata": {"n_personas": n_personas, "n_rounds": n_rounds},
                "file_path": None, "file_content": None, "artifact": False,
            }
            sim_dict: dict = {}
            try:
                engine = SimulationEngine(_sim_llm, max_personas=8, max_rounds=5)
                sim_result = engine.run(topic, seed, n_personas, n_rounds)
                output     = sim_result.report
                sim_dict   = sim_result.to_dict()
            except Exception as _sim_err:
                output = f"Simulation failed: {_sim_err}"
            yield {"type": "simulation", "id": _sim_id, "result": sim_dict}
            yield {
                "type": "tool", "id": _sim_id, "parent_id": None, "status": "done",
                "icon": "🧬", "action": "simulate", "tool_name": "simulate",
                "label": topic[:120], "result": output[:600], "input": action,
                "metadata": {"n_personas": n_personas, "n_rounds": n_rounds},
                "file_path": None, "file_content": None, "artifact": False,
            }
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": f"Simulation complete.\n{output}\n\nContinue."})
            continue

        if kind == "agent_message":
            from .agent_bus import post_message as _bus_post
            from_id  = action.get("from", "agent")
            to_id    = action.get("to", "broadcast")
            content  = action.get("content", "")
            _msg = _bus_post(from_id, to_id, content)
            output = f"Message sent to '{to_id}' (id={_msg.msg_id})"
            yield {
                "type": "tool", "icon": "📨", "action": "agent_message", "tool_name": "agent_message",
                "label": f"→ {to_id}: {content[:80]}", "result": output,
                "file_path": None, "file_content": None, "artifact": False,
            }
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": f"Tool result:\n{output}\n\nContinue."})
            continue

        # Built-in tools (no LLM needed)
        tool_input_verdict = screen_tool_action(action, policy_profile=get_session_safety_profile(sid))
        if tool_input_verdict.action == SafetyAction.BLOCK:
            result = describe_block(tool_input_verdict)
            _tid = f"tool_{int(time.time()*1000)}"
            _evt = {
                "type": "tool", "id": _tid, "parent_id": None,
                "status": "blocked", "icon": TOOL_ICONS.get(kind, "🔧"),
                "action": kind, "tool_name": kind,
                "label": str(action)[:120], "result": result,
                "input": action, "metadata": {"safety": {"input": tool_input_verdict.to_dict()}},
                "file_path": None, "file_content": None, "artifact": False,
            }
            yield _evt
            _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
            _push_activity({"ts": time.time(), "action": kind, "label": str(action)[:120],
                            "status": "blocked", "session": sid})
            _push_safety_event("block", {
                "tool": kind, "label": str(action)[:120], "session": sid,
                "profile": get_session_safety_profile(sid),
                "verdict": tool_input_verdict.to_dict(),
            })
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":f"Tool result:\n{result}\n\nContinue."})
            _step_idx += 1
            if trace_id:
                _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
            continue

        hitl_mode = str(_config.get("hitl_approval_mode", "off") or "off").lower()
        if hitl_mode != "off" and _requires_hitl_checkpoint(kind, action, tool_input_verdict.threat.value):
            approval_id = str(action.get("approval_id", "") or "").strip()
            if not consume_approved_action(approval_id, sid, action):
                new_approval_id = create_tool_approval(sid, action)
                prompt = (
                    f"⏸ Approval required for high-risk action '{kind}'. "
                    f"Use approval_id '{new_approval_id}' via /approvals/{new_approval_id} before retrying."
                )
                yield {
                    "type": "approval_required",
                    "approval_id": new_approval_id,
                    "action": kind,
                    "mode": hitl_mode,
                    "message": prompt,
                }
                _tid = f"tool_{int(time.time()*1000)}"
                _evt = {
                    "type": "tool", "id": _tid, "parent_id": None,
                    "status": "pending_approval", "icon": TOOL_ICONS.get(kind, "🔧"),
                    "action": kind, "tool_name": kind,
                    "label": str(action)[:120], "result": prompt,
                    "input": action,
                    "metadata": {
                        "approval_required": True,
                        "approval_id": new_approval_id,
                        "safety": {"input": tool_input_verdict.to_dict()},
                    },
                    "file_path": None, "file_content": None, "artifact": False,
                }
                yield _evt
                _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
                _push_activity({"ts": time.time(), "action": kind, "label": str(action)[:120],
                                "status": "pending_approval", "session": sid})
                messages.append({"role":"assistant","content":json.dumps(action)})
                messages.append({"role":"user","content":f"Tool result:\n{prompt}\n\nContinue."})
                _step_idx += 1
                if trace_id:
                    _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
                continue

        builtin_result = _dispatch_builtin_traced(action, sid=sid)

        icon  = TOOL_ICONS.get(kind, "🔧")
        label = (action.get("query") or action.get("path") or action.get("cmd") or
                 action.get("url") or action.get("location") or action.get("expr") or
                 action.get("timezone") or kind)

        # ── tool_start telemetry event ────────────────────────────────────────
        _tid_start = f"tool_{int(time.time()*1000)}"
        yield {"type": "tool_start", "id": _tid_start, "action": kind,
               "icon": icon, "label": str(label)[:120],
               "call_id": _tid_start, "input": action}
        _tool_call_count += 1
        # ─────────────────────────────────────────────────────────────────────

        if builtin_result is not None:
            # builtin_result is now a structured trace dict from dispatch_builtin
            result_str  = builtin_result.get("result", "") if isinstance(builtin_result, dict) else str(builtin_result)
            result_stat = builtin_result.get("status", "done") if isinstance(builtin_result, dict) else "done"
            result_meta = builtin_result.get("metadata", {}) if isinstance(builtin_result, dict) else {}
            tool_output_verdict = screen_output(str(result_str))
            result_str = tool_output_verdict.masked_text or str(result_str)
            result_meta = dict(result_meta)
            result_meta["safety"] = {
                "input": tool_input_verdict.to_dict(),
                "output": tool_output_verdict.to_dict(),
            }
            _tid        = f"tool_{int(time.time()*1000)}"
            _evt = {
                "type":"tool", "id":_tid, "parent_id":None,
                "status":result_stat, "icon":icon,
                "action":kind, "tool_name":kind,
                "label":str(label)[:120], "result":str(result_str)[:600],
                "input":action, "metadata":result_meta,
                "file_path":None, "file_content":None, "artifact":False,
            }
            yield _evt
            _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
            _push_activity({"ts": time.time(), "action": kind, "label": str(label)[:120],
                            "status": result_stat, "session": sid})

            _hard = _blocker_reason(kind, result_str)
            if _hard:
                final = _single_shot_blocker_reply(_hard)
                messages.append({"role": "assistant", "content": final})
                cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
                yield {
                    "type": "done",
                    "content": final,
                    "provider": cfg.get("label", "?"),
                    "model": _config["model"] or cfg.get("default_model", "?"),
                    "history": messages,
                    "tokens": {
                        "input": input_token_estimate,
                        "output": _estimate_tokens(final),
                        "total": input_token_estimate + _estimate_tokens(final),
                    },
                }
                return

            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":f"Tool result:\n{result_str}\n\nContinue."})
            _step_idx += 1
            if trace_id:
                _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
            continue

        # File-system tools (need workdir)
        file_content = None
        file_path    = None
        artifact     = False
        try:
            if kind == "write_file":
                file_path    = action.get("path","file.txt")
                fc           = action.get("content","")
                # Capture existing content for diff before overwriting
                _before_content = ""
                _full_path = os.path.join(workdir, file_path)
                if os.path.exists(_full_path):
                    try:
                        with open(_full_path, "r", encoding="utf-8", errors="replace") as _bfh:
                            _before_content = _bfh.read()
                    except Exception:
                        pass
                result       = tool_write_file(file_path, fc, workdir)
                file_content = fc
                artifact     = _is_artifact(file_path, fc)
                # Emit file_diff event when modifying an existing file
                if _before_content and _before_content != fc:
                    _DIFF_LIMIT = 4000
                    yield {
                        "type": "file_diff",
                        "path": file_path,
                        "before": _before_content[:_DIFF_LIMIT],
                        "after": fc[:_DIFF_LIMIT],
                        "truncated": len(_before_content) > _DIFF_LIMIT or len(fc) > _DIFF_LIMIT,
                    }
            elif kind == "read_file":
                file_path = action.get("path","")
                result    = tool_read_file(file_path, workdir)
            elif kind == "list_files":
                result = tool_list_files(action.get("pattern","**/*"), workdir)
            elif kind == "delete_file":
                result = tool_delete_file(action.get("path",""), workdir)
            elif kind == "image_gen":
                result = tool_image_gen(
                    action.get("prompt",""), action.get("width",512), action.get("height",512))
            elif kind == "run_command":
                result = tool_run_command(action.get("cmd",""), workdir)
            elif kind == "read_pdf":
                from .tools_builtin import tool_read_pdf as _tool_read_pdf
                result = _tool_read_pdf(action.get("path",""), workdir)
            elif kind == "read_docx":
                from .tools_builtin import tool_read_docx as _tool_read_docx
                result = _tool_read_docx(action.get("path",""), workdir)
            elif kind == "read_xlsx":
                from .tools_builtin import tool_read_xlsx as _tool_read_xlsx
                result = _tool_read_xlsx(action.get("path",""), workdir)
            elif kind == "read_pptx":
                from .tools_builtin import tool_read_pptx as _tool_read_pptx
                result = _tool_read_pptx(action.get("path",""), workdir)
            elif kind == "create_repo":
                result = tool_create_repo(
                    action.get("name","new-project"),
                    action.get("description",""),
                    bool(action.get("private", False)),
                    session_token,
                    action.get("org",""),
                )
                # Extract clone URL and set as session repo
                import re as _re
                m = _re.search(r'Clone URL: (https://\S+)', result)
                if m and sid:
                    set_session_repo(sid, m.group(1))
            elif kind == "clone_repo":
                url    = action.get("url","")
                repo_name = url.rstrip("/").split("/")[-1].replace(".git","")
                dest_path = action.get("dest_path") or action.get("path") or ""
                if not dest_path:
                    hint = _requested_path_from_text(clean_task)
                    if hint:
                        dest_path = os.path.join(hint, repo_name)
                target_dir = dest_path if dest_path else os.path.join(workdir, repo_name)
                already_cloned = os.path.exists(os.path.join(target_dir, ".git"))
                if already_cloned:
                    result = f"Already cloned at {target_dir} — skipping."
                else:
                    result = tool_clone_repo(url, session_token, workdir, target_dir)
                if sid and "Clone failed" not in result and url:
                    set_session_repo(sid, url)
            elif kind == "commit_push":
                # Use explicit repo_url, then session's active repo — NEVER fall back to GITHUB_REPO
                repo_url = action.get("repo_url") or (get_session_repo(sid) if sid else "")
                result   = tool_commit_push(action.get("message","Update"),
                                            repo_url, session_token, workdir)
            elif kind == "get_time":
                result = tool_get_time(action.get("timezone","UTC"))
            elif kind == "nexus_status":
                result = tool_nexus_status()
            elif kind == "ollama_list_models":
                result = tool_ollama_list_models()
            elif kind == "mcp_call":
                result = tool_mcp_call(action.get("name", ""), action.get("args", {}))
            elif kind == "web_search":
                result = tool_web_search(action.get("query",""))
            else:
                result = f"Unknown action: {kind}"
        except Exception as e:
            err_class   = _classify_tool_error(e)
            retry_delay = _RETRY_DELAYS.get(err_class, 0.0)
            if err_class != "other" and kind in _RETRY_TOOL_KINDS and retry_delay > 0:
                print(f"⚠️ {kind} failed ({err_class}), retrying in {retry_delay:.0f}s…")
                time.sleep(retry_delay)
                try:
                    if   kind == "web_search":
                        result = tool_web_search(action.get("query", ""))
                    else:
                        # re-dispatch via dispatch_builtin (covers read_page, api_call, youtube_*)
                        _br = _dispatch_builtin_traced(action, sid=sid)
                        result = _br["result"] if _br else f"Tool failed after {err_class} retry: {e}"
                except Exception as e2:
                    result = f"Tool failed after {err_class} retry: {e2}"
            else:
                try:
                    if   kind == "write_file":   result = tool_write_file(action.get("path",""), action.get("content",""), workdir)
                    elif kind == "run_command":  result = tool_run_command(action.get("cmd",""), workdir)
                    else:                        result = f"Tool failed: {e}"
                except Exception as e2: result = f"Tool failed after retry: {e2}"

        tool_output_verdict = screen_output(str(result))
        result = tool_output_verdict.masked_text or str(result)
        _tid      = f"tool_{int(time.time()*1000)}"
        _tool_meta = {}
        if file_path:
            _tool_meta["file_path"] = file_path
        if kind in ("run_command", "clone_repo", "commit_push"):
            _tool_meta["workdir"] = workdir
        _tool_meta["safety"] = {
            "input": tool_input_verdict.to_dict(),
            "output": tool_output_verdict.to_dict(),
        }
        _evt = {"type":"tool", "id":_tid, "parent_id":None,
               "status":"done", "icon":icon, "action":kind, "tool_name":kind,
               "label":str(label)[:120], "result":str(result)[:600],
               "input":action, "metadata":_tool_meta,
               "file_path":file_path, "file_content":file_content,
               "artifact":artifact, "workdir":workdir if artifact else None}
        yield _evt
        _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
        _push_activity({"ts": time.time(), "action": kind, "label": str(label)[:120],
                        "status": "done", "session": sid})

        _hard = _blocker_reason(kind, str(result))
        if _hard:
            final = _single_shot_blocker_reply(_hard)
            messages.append({"role": "assistant", "content": final})
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
            yield {
                "type": "done",
                "content": final,
                "provider": cfg.get("label", "?"),
                "model": _config["model"] or cfg.get("default_model", "?"),
                "history": messages,
                "tokens": {
                    "input": input_token_estimate,
                    "output": _estimate_tokens(final),
                    "total": input_token_estimate + _estimate_tokens(final),
                },
            }
            return

        messages.append({"role":"assistant","content":json.dumps(action)})
        messages.append({"role":"user","content":f"Tool result:\n{result}\n\nContinue."})
        _step_idx += 1
        if trace_id:
            _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)

    # Hit MAX_LOOP
    cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
    final = "Reached max steps."
    messages.append({"role":"assistant","content":final})
    yield {"type":"done","content":final,"provider":cfg.get("label","?"),
           "model":_config["model"] or cfg.get("default_model","?"),"history":messages,
           "tokens":{"input":input_token_estimate,"output":1,"total":input_token_estimate+1}}

# ── non-streaming wrapper ─────────────────────────────────────────────────────
def run_agent_task(task, history, files=None, sid=""):
    tool_log, fallback_notice, final = [], "", None
    ensemble_meta: Optional[Dict[str, Any]] = None
    for evt in stream_agent_task(task, history, files, sid=sid):
        if evt["type"]=="tool":        tool_log.append(f"{evt['icon']} **`{evt['action']}`** `{evt['label']}` → {evt['result']}")
        elif evt["type"]=="think":     tool_log.append(f"💭 *{evt['thought']}*")
        elif evt["type"]=="fallback":  fallback_notice = f"*↩️ Auto-fallback: {evt['chain']}*\n\n"
        elif evt["type"]=="ensemble":  ensemble_meta = evt
        elif evt["type"] in ("done","error"): final = evt
    if not final: return {"result":"No response.","history":history,"provider":"?","model":"?"}
    if final["type"]=="error": return {"result":f"❌ {final['message']}","history":history,"provider":"none","model":"none"}
    shown = (fallback_notice + ("\n\n".join(tool_log)+"\n\n---\n\n" if tool_log else "") + final["content"])
    out: Dict[str, Any] = {
        "result": shown,
        "history": final.get("history", history),
        "provider": final["provider"],
        "model": final["model"],
    }
    if ensemble_meta:
        out["ensemble"] = ensemble_meta
    return out


# ── agent warm-up / pre-loading ───────────────────────────────────────────────
_WARMUP_CACHE: Dict[str, Dict[str, Any]] = {}   # sid → {messages, ts}
_WARMUP_TTL = 300                                # seconds before cache expires


def warmup_agent(sid: str = "", persona: str = "") -> Dict[str, Any]:
    """Prime an agent context for a given session so the first real call is faster.

    Performs a lightweight LLM call using the system prompt + a sentinel greeting,
    caches the resulting messages under ``sid``, and returns metadata.
    This reduces cold-start latency when the user sends their first message.
    """
    cache_key = f"{sid}:{persona or _config.get('persona', 'general')}"
    cached = _WARMUP_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _WARMUP_TTL:
        return {"warmed": False, "cached": True, "age_s": round(time.time() - cached["ts"])}

    warmup_msg = [{"role": "user",
                   "content": "System ready. Acknowledge with one word."}]
    try:
        _, pid, _ = call_llm_smart(warmup_msg, "warmup")
        _WARMUP_CACHE[cache_key] = {
            "messages": warmup_msg,
            "provider": pid,
            "ts": time.time(),
        }
        return {"warmed": True, "cached": False, "provider": pid}
    except Exception as exc:
        return {"warmed": False, "cached": False, "error": str(exc)}

# ── UI helpers ────────────────────────────────────────────────────────────────
# ── provider capability matrix ───────────────────────────────────────────────
PROVIDER_CAPABILITIES: Dict[str, Dict[str, bool]] = {
    "ollama":         {"vision": True,  "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "llm7":           {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "groq":           {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "cerebras":       {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "gemini":         {"vision": True,  "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "mistral":        {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "openrouter":     {"vision": True,  "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "nvidia":         {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "cohere":         {"vision": False, "json_mode": True,  "tools": False, "reasoning": False, "streaming": True},
    "github_models":  {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "grok":           {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "claude":         {"vision": True,  "json_mode": False, "tools": True,  "reasoning": True,  "streaming": True},
}

# ── provider benchmark baselines (latency_ms, quality_score 0-100) ─────────────
_PROVIDER_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "ollama":        {"latency_ms": 500,  "quality": 75, "tier": "high",   "cost_tier": "free"},
    "llm7":          {"latency_ms": 2000, "quality": 60, "tier": "low",    "cost_tier": "free"},
    "groq":          {"latency_ms": 800,  "quality": 72, "tier": "medium", "cost_tier": "paid"},
    "cerebras":      {"latency_ms": 1200, "quality": 70, "tier": "medium", "cost_tier": "paid"},
    "gemini":        {"latency_ms": 1500, "quality": 85, "tier": "high",   "cost_tier": "paid"},
    "mistral":       {"latency_ms": 2000, "quality": 80, "tier": "high",   "cost_tier": "paid"},
    "openrouter":    {"latency_ms": 3000, "quality": 80, "tier": "medium", "cost_tier": "paid"},
    "nvidia":        {"latency_ms": 1000, "quality": 78, "tier": "medium", "cost_tier": "paid"},
    "cohere":        {"latency_ms": 2500, "quality": 65, "tier": "low",    "cost_tier": "paid"},
    "github_models": {"latency_ms": 1800, "quality": 75, "tier": "medium", "cost_tier": "free"},
    "grok":          {"latency_ms": 2200, "quality": 82, "tier": "high",   "cost_tier": "paid"},
    "claude":        {"latency_ms": 2800, "quality": 90, "tier": "high",   "cost_tier": "paid"},
}

# ── per-persona provider overrides ────────────────────────────────────────────
_PERSONA_PROVIDER_OVERRIDES: Dict[str, List[str]] = {
    "general":   ["ollama", "claude", "gemini", "grok", "openrouter"],
    "coder":     ["ollama", "claude", "groq", "cerebras", "github_models"],
    "researcher": ["gemini", "grok", "openrouter", "claude", "mistral"],
    "creative":  ["claude", "gemini", "mistral", "openrouter"],
    "architect": ["claude", "grok", "gemini", "openrouter"],
}

def get_provider_health() -> Dict[str, Any]:
    """Return health status for all providers including rate limit state."""
    result = []
    for pid, cfg in PROVIDERS.items():
        has_key = _has_key(cfg)
        is_limited = _is_rate_limited(pid)
        cooldown_secs = max(0, int(_cooldowns.get(pid, 0) - time.time()))
        benchmarks = _PROVIDER_BENCHMARKS.get(pid, {})
        
        result.append({
            "id": pid,
            "label": cfg["label"],
            "status": "rate_limited" if is_limited else ("ready" if has_key else "unconfigured"),
            "available": has_key and not is_limited,
            "has_api_key": has_key,
            "keyless": cfg.get("keyless", False),
            "local": cfg.get("local", False),
            "rate_limited": is_limited,
            "cooldown_remaining_seconds": cooldown_secs,
            "capabilities": PROVIDER_CAPABILITIES.get(pid, {}),
            "benchmarks": {
                "estimated_latency_ms": benchmarks.get("latency_ms", 0),
                "quality_score": benchmarks.get("quality", 0),
                "tier": benchmarks.get("tier", "unknown"),
                "cost_tier": benchmarks.get("cost_tier", "unknown"),
            },
            "openai_compat": cfg.get("openai_compat", False),
            "default_model": cfg.get("default_model", ""),
        })
    return {"providers": result, "timestamp": time.time()}

def get_provider_capabilities() -> Dict[str, Any]:
    """Return capability matrix for all providers."""
    return {
        "capabilities": {
            "vision": "Supports image input and vision understanding",
            "json_mode": "Supports JSON response format enforcement",
            "tools": "Supports tool/function calling",
            "reasoning": "Supports chain-of-thought and reasoning",
            "streaming": "Supports streaming responses",
        },
        "providers": {
            pid: caps for pid, caps in PROVIDER_CAPABILITIES.items()
        },
    }

def set_provider_persona_override(persona: str, provider_order: List[str]) -> bool:
    """Set a custom provider priority order for a specific persona."""
    if persona not in PERSONAS:
        return False
    valid_providers = set(PROVIDERS.keys())
    if not all(p in valid_providers for p in provider_order):
        return False
    _PERSONA_PROVIDER_OVERRIDES[persona] = provider_order
    return True

def get_provider_persona_override(persona: str) -> Optional[List[str]]:
    """Get the custom provider order for a persona, or None if using default."""
    return _PERSONA_PROVIDER_OVERRIDES.get(persona)

def get_providers_list():
    result = []
    for pid, cfg in PROVIDERS.items():
        has_key = _has_key(cfg)
        cooling = _is_rate_limited(pid)
        result.append({"id":pid,"label":cfg["label"],
                       "model":_config["model"] or cfg["default_model"],
                       "available":has_key and not cooling,"has_key":has_key,
                       "rate_limited":cooling,
                       "cooldown_remaining":max(0,int(_cooldowns.get(pid,0)-time.time())),
                       "keyless":cfg.get("keyless",False),
                       "openai_compat":cfg.get("openai_compat",False),
                       "local":cfg.get("local",False)})
    return result
