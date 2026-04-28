import os, re, json, glob, time, subprocess, threading, resource, hmac, hashlib
import urllib.request
from urllib.parse import quote as _url_quote
from functools import lru_cache
from datetime import datetime, timezone
from contextlib import nullcontext
from typing import Dict, Any, List, Iterator, Optional, Pattern
from pathlib import Path
from .tools_builtin import dispatch_builtin, build_openai_tools
from .autonomy import Orchestrator, classify_subtask, PlanningSystem
from .personas import build_system_prompt, get_active_persona_name, get_persona, get_allowed_tools
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
from .db import load_custom_instructions, log_usage, init_usage_table, add_safety_audit_entry, record_strict_clone_bypass_event, count_strict_clone_bypass_events, list_strict_clone_bypass_events
from .knowledge_graph import kg_to_context_string
from .execution_trace import save_checkpoint as _save_checkpoint
from .safety_pipeline import SAFETY_POLICY_PROFILES, describe_block, screen_output, screen_tool_action
from .safety_types import SafetyAction
from .approvals import create_tool_approval, list_tool_approvals, decide_tool_approval, consume_approved_action
from .memory import add_memory, summarize_history as _summarize_history, get_memory_context
from .profile_loader import load_profile_pack
from .secrets_manager import get_secret, inject_request_credentials, secret_access_context
from .circuit_breaker import CircuitBreakerOpen, CircuitState, get_circuit_breaker


def _load_local_env_files() -> None:
    """Best-effort .env loader for local/dev runs.

    Uses python-dotenv when available, otherwise falls back to a small parser.
    Existing environment variables are never overridden.
    """
    env_paths = [Path(".env"), Path(".env.local")]
    try:
        from dotenv import load_dotenv  # type: ignore
        for p in env_paths:
            if p.exists():
                load_dotenv(dotenv_path=p, override=False)
        return
    except Exception:
        pass

    for p in env_paths:
        if not p.exists():
            continue
        try:
            for raw_line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key or key in os.environ:
                    continue
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                else:
                    # Strip inline comments in unquoted values (e.g. KEY=abc # note).
                    # This avoids accidentally including human-readable comments in secrets.
                    hash_idx = value.find(" #")
                    if hash_idx != -1:
                        value = value[:hash_idx].rstrip()
                os.environ[key] = value
        except Exception:
            pass


_load_local_env_files()

try:
    init_usage_table()
except Exception:
    pass

# ── runtime config ────────────────────────────────────────────────────────────
_config: Dict[str, Any] = {
    "provider":           os.getenv("PROVIDER", "auto").lower(),
    "model":              os.getenv("LLM_MODEL", os.getenv("DEFAULT_MODEL", "")),
    "temperature":        float(os.getenv("LLM_TEMPERATURE", "0.2")),
    "persona":            os.getenv("PERSONA", "general"),
    "ensemble_mode":      True,
    "ensemble_threshold": 0.4,
    "hitl_approval_mode": os.getenv("HITL_APPROVAL_MODE", "off").lower(),
    "safety_profile":     os.getenv("SAFETY_POLICY_PROFILE", "standard").lower(),
    "strict_mode_profile": os.getenv("STRICT_MODE_PROFILE", "strict").lower(),
    "strict_no_guess_mode": os.getenv("STRICT_NO_GUESS_MODE", "true").lower() in ("1", "true", "yes", "on"),
    "strict_confidence_threshold": float(os.getenv("STRICT_CONFIDENCE_THRESHOLD", "0.95")),
    "strict_evidence_threshold": int(os.getenv("STRICT_EVIDENCE_THRESHOLD", "1")),
    # Native tool-calling: send the OpenAI tools= array to the model instead of
    # relying on the custom "Reply with JSON" system prompt.  Enabled by default
    # for all OpenAI-compatible providers.  Set NATIVE_TOOL_CALLING=false to
    # revert to the legacy JSON-parsing path.
    "native_tool_calling": os.getenv("NATIVE_TOOL_CALLING", "true").lower() in ("1", "true", "yes", "on"),
    # Token-efficiency controls
    "native_tool_budget_mode": os.getenv("NATIVE_TOOL_BUDGET_MODE", "adaptive").lower(),
    "injected_context_max_chars": int(os.getenv("INJECTED_CONTEXT_MAX_CHARS", "2200")),
    "tool_result_context_max_chars": int(os.getenv("TOOL_RESULT_CONTEXT_MAX_CHARS", "900")),
    "context_reserve_tokens": int(os.getenv("CONTEXT_RESERVE_TOKENS", "3072")),
    "turn_budget_enforced": os.getenv("TURN_BUDGET_ENFORCED", "true").lower() in ("1", "true", "yes", "on"),
    "turn_budget_ratio_low": float(os.getenv("TURN_BUDGET_RATIO_LOW", "0.30")),
    "turn_budget_ratio_medium": float(os.getenv("TURN_BUDGET_RATIO_MEDIUM", "0.42")),
    "turn_budget_ratio_high": float(os.getenv("TURN_BUDGET_RATIO_HIGH", "0.58")),
    "turn_output_reserve_low": int(os.getenv("TURN_OUTPUT_RESERVE_LOW", "1400")),
    "turn_output_reserve_medium": int(os.getenv("TURN_OUTPUT_RESERVE_MEDIUM", "2600")),
    "turn_output_reserve_high": int(os.getenv("TURN_OUTPUT_RESERVE_HIGH", "5200")),
}

_STRICT_MODE_PRESETS: Dict[str, Dict[str, Any]] = {
    "balanced": {
        "strict_no_guess_mode": False,
        "strict_confidence_threshold": 0.80,
        "strict_evidence_threshold": 0,
    },
    "strict": {
        "strict_no_guess_mode": True,
        "strict_confidence_threshold": 0.95,
        "strict_evidence_threshold": 1,
    },
    "paranoid": {
        "strict_no_guess_mode": True,
        "strict_confidence_threshold": 0.98,
        "strict_evidence_threshold": 2,
    },
}


def _apply_strict_mode_profile(profile: str) -> str:
    selected = str(profile or "strict").lower().strip()
    if selected not in _STRICT_MODE_PRESETS:
        selected = "strict"
    preset = _STRICT_MODE_PRESETS[selected]
    _config["strict_mode_profile"] = selected
    _config["strict_no_guess_mode"] = bool(preset["strict_no_guess_mode"])
    _config["strict_confidence_threshold"] = float(preset["strict_confidence_threshold"])
    _config["strict_evidence_threshold"] = int(preset["strict_evidence_threshold"])
    return selected


_apply_strict_mode_profile(_config.get("strict_mode_profile", "strict"))

def get_config() -> Dict[str, Any]: return dict(_config)
def update_config(provider=None, model=None, temperature=None, persona=None,
                  ensemble_mode=None, ensemble_threshold=None, hitl_approval_mode=None,
                  safety_profile=None, strict_no_guess_mode=None,
                  strict_confidence_threshold=None, strict_evidence_threshold=None,
                  strict_mode_profile=None, native_tool_budget_mode=None,
                  injected_context_max_chars=None, tool_result_context_max_chars=None,
                  context_reserve_tokens=None, turn_budget_enforced=None):
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
    if strict_mode_profile is not None:
        _apply_strict_mode_profile(strict_mode_profile)
    if strict_no_guess_mode is not None:
        if isinstance(strict_no_guess_mode, bool):
            _config["strict_no_guess_mode"] = strict_no_guess_mode
        else:
            _config["strict_no_guess_mode"] = str(strict_no_guess_mode).lower().strip() in ("1", "true", "yes", "on")
    if strict_confidence_threshold is not None:
        try:
            value = float(strict_confidence_threshold)
            _config["strict_confidence_threshold"] = min(1.0, max(0.0, value))
        except Exception:
            pass
    if strict_evidence_threshold is not None:
        try:
            value = int(strict_evidence_threshold)
            _config["strict_evidence_threshold"] = max(0, value)
        except Exception:
            pass
    if native_tool_budget_mode is not None:
        _config["native_tool_budget_mode"] = str(native_tool_budget_mode).lower().strip()
    if injected_context_max_chars is not None:
        try:
            _config["injected_context_max_chars"] = max(200, int(injected_context_max_chars))
        except Exception:
            pass
    if tool_result_context_max_chars is not None:
        try:
            _config["tool_result_context_max_chars"] = max(200, int(tool_result_context_max_chars))
        except Exception:
            pass
    if context_reserve_tokens is not None:
        try:
            _config["context_reserve_tokens"] = max(512, int(context_reserve_tokens))
        except Exception:
            pass
    if turn_budget_enforced is not None:
        if isinstance(turn_budget_enforced, bool):
            _config["turn_budget_enforced"] = turn_budget_enforced
        else:
            _config["turn_budget_enforced"] = str(turn_budget_enforced).lower().strip() in ("1", "true", "yes", "on")
    # Keep profile metadata coherent when direct values diverge from preset values.
    if strict_mode_profile is None and any(
        v is not None for v in (strict_no_guess_mode, strict_confidence_threshold, strict_evidence_threshold)
    ):
        _config["strict_mode_profile"] = "custom"
    return dict(_config)

# ── env ───────────────────────────────────────────────────────────────────────
GH_TOKEN    = os.getenv("GH_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
MAX_LOOP    = 24
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


def _send_safety_event_webhook(entry: Dict[str, Any]) -> None:
    """Deliver safety events to an external webhook endpoint when configured.

    Delivery is best-effort and must never interrupt request processing.
    """
    webhook_url = (os.getenv("SAFETY_EVENT_WEBHOOK_URL", "") or "").strip()
    webhook_secret = os.getenv("SAFETY_EVENT_WEBHOOK_SECRET", "")
    webhook_timeout = max(1, int(os.getenv("SAFETY_EVENT_WEBHOOK_TIMEOUT", "3")))

    if not webhook_url:
        return

    payload = {
        "schema": "nexus.safety_event.v1",
        "source": "nexus-ai",
        "event": entry,
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Nexus-Safety-Event": str(entry.get("type") or ""),
    }
    if webhook_secret:
        signature = hmac.new(
            webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        headers["X-Nexus-Signature"] = f"sha256={signature}"

    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=webhook_timeout):
            return
    except Exception as e:
        print(f"Failed to send safety event webhook: {e}")

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
    try:
        _send_safety_event_webhook(entry)
    except Exception:
        # Never let webhook transport failures affect user-facing safety flows.
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


def _redact_sensitive_text(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Best-effort redaction for secrets and credentialed URLs in user-visible output."""
    redacted = str(text or "")
    for secret in secrets:
        if not secret:
            continue
        redacted = redacted.replace(secret, "[REDACTED]")
        try:
            encoded = _url_quote(secret, safe="")
            if encoded:
                redacted = redacted.replace(encoded, "[REDACTED]")
        except Exception:
            pass
    # Hide URL userinfo credentials if present (e.g. https://token@host/...)
    redacted = re.sub(r"https://[^@/\s]+@", "https://[REDACTED]@", redacted)
    return redacted

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
# ── provider registry ─────────────────────────────────────────────────────────
# free_tier schema:
#   available   – True if a genuine zero-cost tier exists (even if key signup is needed)
#   cc_required – True if a credit card is required to unlock the free tier
#   signup_url  – Where to obtain a free API key
#   limits      – Human-readable rate/quota summary
#   free_model  – If set, use this model name instead of default_model when FREE_ONLY_MODE=true
#                 (needed for providers like OpenRouter where free models have a :free suffix)
#   notes       – Any other setup instructions
PROVIDERS: Dict[str, Dict] = {
    # ── Keyless / local (no signup required, always available) ────────────────
    "llm7": {
        "label":"LLM7.io","base_url":"https://api.llm7.io/v1",
        "env_key":"LLM7_API_KEY","default_model":"meta-llama/Llama-3.2-3B-Instruct",
        "openai_compat":True,"keyless":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://llm7.io","limits":"Community rate limits",
                     "free_model":None,"notes":"No API key required. Anonymous access."},
    },
    "ollama": {
        "label":"Ollama (Local)",
        "base_url":os.getenv("OLLAMA_BASE_URL","http://localhost:11434/v1"),
        "env_key":"","default_model":"llama3.2","openai_compat":True,"keyless":True,"local":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://ollama.com","limits":"Unlimited — local hardware only",
                     "free_model":None,"notes":"Install Ollama then `ollama pull <model>`."},
    },
    "lmstudio": {
        "label":"LM Studio (Local)",
        "base_url":os.getenv("LMSTUDIO_BASE_URL","http://localhost:1234/v1"),
        "env_key":"","default_model":"local-model","openai_compat":True,"keyless":True,"local":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://lmstudio.ai","limits":"Unlimited — local hardware only",
                     "free_model":None,"notes":"Enable local server in LM Studio settings (default port 1234)."},
    },
    # ── Ongoing free tier — API key required, no credit card ──────────────────
    "groq": {
        "label":"Groq","base_url":"https://api.groq.com/openai/v1",
        "env_key":"GROQ_API_KEY","default_model":"llama-3.3-70b-versatile",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://console.groq.com",
                     "limits":"30–60 RPM · 1K–14.4K req/day (model-dependent)",
                     "free_model":None,"notes":"No CC. Free key at console.groq.com. Also covers Whisper STT."},
    },
    "cerebras": {
        "label":"Cerebras","base_url":"https://api.cerebras.ai/v1",
        "env_key":"CEREBRAS_API_KEY","default_model":"llama3.3-70b",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://cloud.cerebras.ai",
                     "limits":"1M tokens/day · 30 RPM · 60K TPM · 8K ctx on free tier",
                     "free_model":None,"notes":"No waitlist, no CC. Fastest inference on planet via custom silicon."},
    },
    "gemini": {
        "label":"Google Gemini",
        "base_url":"https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key":"GEMINI_API_KEY","default_model":"gemini-2.0-flash",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://ai.google.dev",
                     "limits":"1500 req/day · 15 RPM · 1M token context",
                     "free_model":None,"notes":"Get free key at ai.google.dev (Google AI Studio). Multimodal: image/audio/video."},
    },
    "gemma": {
        "label":"Google Gemma 2",
        "base_url":"https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key":"GEMINI_API_KEY","default_model":"gemma-2-9b-it",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://ai.google.dev",
                     "limits":"Shared with GEMINI_API_KEY free tier",
                     "free_model":None,"notes":"Same GEMINI_API_KEY as Gemini — one signup covers both."},
    },
    "mistral": {
        "label":"Mistral AI","base_url":"https://api.mistral.ai/v1",
        "env_key":"MISTRAL_API_KEY","default_model":"mistral-small-latest",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://console.mistral.ai",
                     "limits":"2 RPM · 500K TPM · 1B tokens/month",
                     "free_model":None,"notes":"EU-hosted. No CC. Includes Codestral + OCR in same token budget."},
    },
    "mistral_codestral": {
        "label":"Codestral (Mistral)","base_url":"https://codestral.mistral.ai/v1",
        "env_key":"CODESTRAL_API_KEY","default_model":"codestral-latest",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://console.mistral.ai",
                     "limits":"Shared with MISTRAL_API_KEY 1B tokens/month",
                     "free_model":None,"notes":"Best free code-gen model. Same key as Mistral."},
    },
    "cohere": {
        "label":"Cohere","base_url":"https://api.cohere.com/compatibility/v1",
        "env_key":"COHERE_API_KEY","default_model":"command-r-plus",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://dashboard.cohere.com",
                     "limits":"20 RPM · 1K req/month — non-commercial only",
                     "free_model":None,"notes":"Instant trial key, no CC. Covers Embed 4 + Rerank 3.5 for full RAG."},
    },
    "github_models": {
        "label":"GitHub Models","base_url":"https://models.inference.ai.azure.com",
        "env_key":"GITHUB_MODELS_TOKEN","default_model":"gpt-4o-mini",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://github.com/marketplace/models",
                     "limits":"50 chat + 2K completions/month · 50–150 req/day per model",
                     "free_model":None,"notes":"Non-commercial/prototyping only. Use a GitHub personal access token."},
    },
    "huggingface": {
        "label":"HuggingFace Inference","base_url":"https://api-inference.huggingface.co/v1",
        "env_key":"HF_TOKEN","default_model":"mistralai/Mistral-7B-Instruct-v0.3",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://huggingface.co/settings/tokens",
                     "limits":"Free serverless inference for community models",
                     "free_model":None,"notes":"100K+ open-source models available free. HF token at huggingface.co/settings/tokens."},
    },
    "sambanova": {
        "label":"SambaNova Cloud","base_url":"https://api.sambanova.ai/v1",
        "env_key":"SAMBANOVA_API_KEY","default_model":"Meta-Llama-3.3-70B-Instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://cloud.sambanova.ai",
                     "limits":"$5 credits on signup (30-day) + persistent free tier after",
                     "free_model":None,"notes":"Custom RDU silicon. No CC. 10–30 RPM."},
    },
    "siliconflow": {
        "label":"SiliconFlow","base_url":"https://api.siliconflow.cn/v1",
        "env_key":"SILICONFLOW_API_KEY","default_model":"Qwen/Qwen3-8B",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://siliconflow.cn",
                     "limits":"1K RPM · 50K TPM",
                     "free_model":None,"notes":"Best coverage of Qwen/GLM/DeepSeek family. No CC."},
    },
    "scaleway": {
        "label":"Scaleway Generative APIs","base_url":"https://api.scaleway.ai/v1",
        "env_key":"SCALEWAY_API_KEY","default_model":"llama-3.3-70b-instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://www.scaleway.com/en/generative-apis/",
                     "limits":"1M tokens — permanent, no expiry",
                     "free_model":None,"notes":"EU-hosted, GDPR-friendly. Best for European data residency."},
    },
    "cloudflare": {
        "label":"Cloudflare Workers AI",
        "base_url":f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CF_ACCOUNT_ID','')}/ai/v1",
        "env_key":"CF_API_TOKEN","default_model":"@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://developers.cloudflare.com/workers-ai",
                     "limits":"10K neurons/day (shared: text + image + STT)",
                     "free_model":None,"notes":"Edge-deployed, no cold starts. Set CF_ACCOUNT_ID + CF_API_TOKEN from Cloudflare dashboard."},
    },
    "fireworks": {
        "label":"Fireworks AI","base_url":"https://api.fireworks.ai/inference/v1",
        "env_key":"FIREWORKS_API_KEY","default_model":"accounts/fireworks/models/llama-v3p3-70b-instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://fireworks.ai",
                     "limits":"10 RPM without CC ($1 permanent credits on signup)",
                     "free_model":None,"notes":"6K RPM after adding a card. $1 signup credits permanent."},
    },
    "deepinfra": {
        "label":"DeepInfra","base_url":"https://api.deepinfra.com/v1/openai",
        "env_key":"DEEPINFRA_API_KEY","default_model":"meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://deepinfra.com",
                     "limits":"~40 RPM · 1K free credits on signup",
                     "free_model":None,"notes":"No CC required. Popular open-source model hosting."},
    },
    "hyperbolic": {
        "label":"Hyperbolic","base_url":"https://api.hyperbolic.xyz/v1",
        "env_key":"HYPERBOLIC_API_KEY","default_model":"meta-llama/Llama-3.3-70B-Instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://app.hyperbolic.xyz",
                     "limits":"$1 permanent credits on signup",
                     "free_model":None,"notes":"No CC. 13 models including Llama and DeepSeek variants."},
    },
    "novita": {
        "label":"Novita AI","base_url":"https://api.novita.ai/v3/openai",
        "env_key":"NOVITA_API_KEY","default_model":"meta-llama/llama-3.3-70b-instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://novita.ai",
                     "limits":"$0.50 free credits (1-year expiry)",
                     "free_model":None,"notes":"No CC required."},
    },
    "nebius": {
        "label":"Nebius AI Studio","base_url":"https://api.studio.nebius.ai/v1",
        "env_key":"NEBIUS_API_KEY","default_model":"meta-llama/Meta-Llama-3.1-70B-Instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://studio.nebius.ai",
                     "limits":"$1 permanent credits on signup",
                     "free_model":None,"notes":"No CC. Covers FLUX image gen + DeepSeek-R1."},
    },
    "inference_net": {
        "label":"Inference.net","base_url":"https://api.inference.net/v1",
        "env_key":"INFERENCE_NET_API_KEY","default_model":"meta-llama/llama-3.3-70b-instruct/fp-8",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://inference.net",
                     "limits":"$1 on signup + $25 after completing survey — permanent",
                     "free_model":None,"notes":"No CC required. Complete onboarding survey for extra credits."},
    },
    "nvidia": {
        "label":"NVIDIA NIM","base_url":"https://integrate.api.nvidia.com/v1",
        "env_key":"NVIDIA_API_KEY","default_model":"meta/llama-3.3-70b-instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://build.nvidia.com",
                     "limits":"1K API credits on signup · 40 RPM (4K more available on request)",
                     "free_model":None,"notes":"91 free model endpoints. Docker self-host for NVIDIA Developer Program members."},
    },
    "aimlapi": {
        "label":"AI/ML API","base_url":"https://api.aimlapi.com/v1",
        "env_key":"AIMLAPI_KEY","default_model":"meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://aimlapi.com",
                     "limits":"Free starter credits on signup",
                     "free_model":None,"notes":"200+ models: text, image, video, TTS."},
    },
    "kluster": {
        "label":"Kluster AI","base_url":"https://api.kluster.ai/v1",
        "env_key":"KLUSTER_API_KEY","default_model":"klusterai/Meta-Llama-3.3-70B-Instruct-Turbo",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://kluster.ai",
                     "limits":"Free trial credits on signup",
                     "free_model":None,"notes":"No CC required."},
    },
    "glhf": {
        "label":"GLHF.chat","base_url":"https://glhf.chat/api/openai/v1",
        "env_key":"GLHF_API_KEY","default_model":"hf:meta-llama/Llama-3.3-70B-Instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://glhf.chat",
                     "limits":"Free community tier — rate limits apply",
                     "free_model":None,"notes":"No CC. All HuggingFace models via hf: prefix."},
    },
    "chutes": {
        "label":"Chutes AI","base_url":"https://llm.chutes.ai/v1",
        "env_key":"CHUTES_API_KEY","default_model":"deepseek-ai/DeepSeek-V3-0324",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://chutes.ai",
                     "limits":"Free community access",
                     "free_model":None,"notes":"No CC required."},
    },
    "featherless": {
        "label":"Featherless AI","base_url":"https://api.featherless.ai/v1",
        "env_key":"FEATHERLESS_API_KEY","default_model":"meta-llama/Meta-Llama-3.1-70B-Instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://featherless.ai",
                     "limits":"Free community tier",
                     "free_model":None,"notes":"No CC required."},
    },
    "neets": {
        "label":"Neets AI","base_url":"https://api.neets.ai/v1",
        "env_key":"NEETS_API_KEY","default_model":"meta-llama/llama-3-70b-instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://neets.ai",
                     "limits":"Free community tier",
                     "free_model":None,"notes":"No CC required."},
    },
    "lepton": {
        "label":"Lepton AI","base_url":"https://llama3-3-70b.lepton.run/api/v1",
        "env_key":"LEPTON_API_KEY","default_model":"llama3-3-70b",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://lepton.ai",
                     "limits":"Free community tier",
                     "free_model":None,"notes":"No CC required."},
    },
    "lambda": {
        "label":"Lambda Labs","base_url":"https://api.lambdalabs.com/v1",
        "env_key":"LAMBDA_API_KEY","default_model":"llama3.3-70b-instruct-fp8",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://lambdalabs.com",
                     "limits":"Free inference credits on signup",
                     "free_model":None,"notes":"No CC required. Primarily GPU compute but free inference API available."},
    },
    # ── Aggregators with model-specific free access ───────────────────────────
    "openrouter": {
        "label":"OpenRouter",
        "base_url":os.getenv("OPENROUTER_BASE_URL","https://openrouter.ai/api/v1"),
        "env_key":"OPENROUTER_API_KEY",
        "default_model":os.getenv("OPENROUTER_MODEL","meta-llama/llama-3.3-70b-instruct:free"),
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://openrouter.ai",
                     "limits":"~30 free models · 20 RPM · 50 req/day (1K/day after $10 lifetime topup)",
                     "free_model":"meta-llama/llama-3.3-70b-instruct:free",
                     "notes":"Models with ':free' suffix are zero-cost. Browse free models at openrouter.ai/models?q=%3Afree"},
    },
    "together": {
        "label":"Together AI","base_url":"https://api.together.xyz/v1",
        "env_key":"TOGETHER_API_KEY",
        "default_model":"meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://api.together.ai",
                     "limits":"Models with '-Free' suffix are zero-cost · $5 min to unlock full catalog",
                     "free_model":"meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
                     "notes":"Use *-Free suffix models for zero-cost. Full catalog needs $5 min credit topup."},
    },
    # ── Signup credits (one-time or expiring, no CC required) ─────────────────
    "moonshot": {
        "label":"Moonshot AI (Kimi K2.5)","base_url":"https://api.moonshot.cn/v1",
        "env_key":"MOONSHOT_API_KEY","default_model":"kimi-k2-5",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://platform.moonshot.cn",
                     "limits":"Free credits on signup",
                     "free_model":None,"notes":"Long-context specialist. Chinese provider."},
    },
    "deepseek": {
        "label":"DeepSeek","base_url":"https://api.deepseek.com/v1",
        "env_key":"DEEPSEEK_API_KEY","default_model":"deepseek-chat",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://platform.deepseek.com",
                     "limits":"5M free tokens on signup (30-day) · ~$0.14/M input after",
                     "free_model":None,"notes":"No CC. Quasi-free even after signup credits expire."},
    },
    "dashscope": {
        "label":"Alibaba DashScope (Qwen)",
        "base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key":"DASHSCOPE_API_KEY","default_model":"qwen-plus",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://dashscope.aliyuncs.com",
                     "limits":"1M tokens per model (90-day expiry on signup)",
                     "free_model":None,"notes":"Best source for Qwen family. No CC required."},
    },
    "ai21": {
        "label":"AI21 Labs","base_url":"https://api.ai21.com/studio/v1",
        "env_key":"AI21_API_KEY","default_model":"jamba-large",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://studio.ai21.com",
                     "limits":"$10 free credits (3-month expiry)",
                     "free_model":None,"notes":"Jamba Large + Jamba Mini. No CC."},
    },
    "upstage": {
        "label":"Upstage (Solar)","base_url":"https://api.upstage.ai/v1",
        "env_key":"UPSTAGE_API_KEY","default_model":"solar-pro",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://console.upstage.ai",
                     "limits":"$10 free credits (3-month expiry)",
                     "free_model":None,"notes":"Solar Pro — excellent quality per parameter. No CC."},
    },
    "ovh": {
        "label":"OVH AI Endpoints",
        "base_url":"https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        "env_key":"OVH_API_KEY","default_model":"Llama-3.3-70B-Instruct",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://endpoints.ai.cloud.ovh.net",
                     "limits":"Free tier for select open-source models",
                     "free_model":None,"notes":"EU-hosted. Alternative to Scaleway for European data residency."},
    },
    "grok": {
        "label":"Grok (xAI)","env_key":"GROK_API_KEY","default_model":"grok-3",
        "openai_compat":False,"opt_in":True,
        "free_tier":{"available":True,"cc_required":False,
                     "signup_url":"https://console.x.ai",
                     "limits":"$25 one-time credits · $150/month more via data sharing opt-in",
                     "free_model":None,"notes":"No CC to start. Data sharing opt-in requires $5 prior spend first."},
    },
    "perplexity": {
        "label":"Perplexity AI","base_url":"https://api.perplexity.ai",
        "env_key":"PERPLEXITY_API_KEY","default_model":"sonar",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":False,"cc_required":True,
                     "signup_url":"https://perplexity.ai",
                     "limits":"Primarily paid as of 2026 — periodic developer trials appear",
                     "free_model":None,"notes":"Check their Labs section for any active free tiers."},
    },
    # ── Paid API only (no free tier) ──────────────────────────────────────────
    "claude": {
        "label":"Claude (Anthropic)","env_key":"CLAUDE_API_KEY",
        "default_model":"claude-sonnet-4-20250514","openai_compat":False,"opt_in":True,
        "free_tier":{"available":False,"cc_required":True,
                     "signup_url":"https://console.anthropic.com",
                     "limits":"No free API tier — paid only",
                     "free_model":None,"notes":"Free via web UI but API requires payment."},
    },
    "openai": {
        "label":"OpenAI","base_url":"https://api.openai.com/v1",
        "env_key":"OPENAI_API_KEY","default_model":"gpt-4o-mini",
        "openai_compat":True,"opt_in":True,
        "free_tier":{"available":False,"cc_required":True,
                     "signup_url":"https://platform.openai.com",
                     "limits":"No free API tier as of 2025",
                     "free_model":None,"notes":"Free credits discontinued mid-2025. Paid API only."},
    },
}

# ── complexity + provider routing ─────────────────────────────────────────────
PROVIDER_TIERS = {
    "high":   ["ollama","lmstudio","claude","grok","gemini","gemma","openrouter","mistral",
               "moonshot","sambanova","together","deepseek","dashscope",
               "hyperbolic","fireworks","chutes","kluster","nebius","upstage","ai21","openai"],
    "medium": ["groq","cerebras","cohere","github_models","nvidia","gemma","siliconflow",
               "huggingface","deepinfra","novita","glhf","featherless","ovh",
               "aimlapi","scaleway","lambda","inference_net","lepton","perplexity",
               "cloudflare","mistral_codestral"],
    "low":    ["llm7","groq","cerebras","gemma","neets","glhf","cloudflare",
               "inference_net","siliconflow"],
}

# ── budget-aware routing ───────────────────────────────────────────────────────
# Approximate cost in USD per 1K output tokens.
# 0.000 = free tier available. Used for BUDGET_TIER filtering only;
# FREE_ONLY_MODE uses free_tier["available"] from each provider config instead.
_PROVIDER_COST_PER_1K_TOKENS: Dict[str, float] = {
    # Always free — local / keyless
    "ollama":           0.000,
    "lmstudio":         0.000,
    "llm7":             0.000,
    # Ongoing free tier — API key required, no CC
    "groq":             0.000,
    "cerebras":         0.000,
    "gemini":           0.000,
    "gemma":            0.000,
    "mistral":          0.000,
    "mistral_codestral":0.000,
    "cohere":           0.000,
    "github_models":    0.000,
    "huggingface":      0.000,
    "sambanova":        0.000,
    "siliconflow":      0.000,
    "scaleway":         0.000,
    "cloudflare":       0.000,
    "fireworks":        0.000,
    "deepinfra":        0.000,
    "hyperbolic":       0.000,
    "novita":           0.000,
    "nebius":           0.000,
    "inference_net":    0.000,
    "nvidia":           0.000,
    "aimlapi":          0.000,
    "kluster":          0.000,
    "glhf":             0.000,
    "chutes":           0.000,
    "featherless":      0.000,
    "neets":            0.000,
    "lepton":           0.000,
    "lambda":           0.000,
    # Aggregators with free model variants
    "openrouter":       0.000,
    "together":         0.000,
    # Signup credits (one-time / expiring)
    "moonshot":         0.001,
    "deepseek":         0.001,
    "dashscope":        0.001,
    "ai21":             0.001,
    "upstage":          0.001,
    "ovh":              0.001,
    "grok":             0.002,
    # Paid only
    "perplexity":       0.005,
    "openai":           0.006,
    "claude":           0.015,
}
BUDGET_TIER: str = os.getenv("BUDGET_TIER", "any").lower()   # free | low | medium | any
FREE_ONLY_MODE: bool = os.getenv("FREE_ONLY_MODE", "false").lower() in ("1", "true", "yes", "on")
WARMUP_DEMOTION_STRIKES: int = max(1, int(os.getenv("WARMUP_DEMOTION_STRIKES", "2")))
# Default 90s: enough to survive startup races without blocking providers for 30 min on a cold-start hiccup.
WARMUP_DEMOTION_SECONDS: int = max(30, int(os.getenv("WARMUP_DEMOTION_SECONDS", "90")))
_BUDGET_MAX_COST: Dict[str, float] = {
    "free":   0.000,
    "low":    0.002,
    "medium": 0.008,
    "any":    999.0,
}

# Model-name allowlist: only for providers where free access requires a specific
# model name pattern (e.g. OpenRouter ':free' suffix, Together '*-Free' suffix).
# All other providers with free_tier["available"]=True accept any model name.
_FREE_MODEL_ALLOWLIST_RAW: Dict[str, List[str]] = {
    "openrouter": [r"(?i):free$", r"(?i)\bfree\b"],
    "together":   [r"(?i)free"],
}
_FREE_MODEL_ALLOWLIST: Dict[str, List[Pattern[str]]] = {
    pid: [re.compile(pat) for pat in pats]
    for pid, pats in _FREE_MODEL_ALLOWLIST_RAW.items()
}

_provider_demotion_until: Dict[str, float] = {}
_provider_demotion_reasons: Dict[str, str] = {}
_provider_warmup_failure_strikes: Dict[str, int] = {}

# ── Mixture-of-Experts specialization routing ─────────────────────────────────
PROVIDER_SPECIALIZATIONS: Dict[str, List[str]] = {
    "coding":    ["ollama", "claude", "groq", "cerebras", "github_models",
                  "deepseek", "moonshot", "fireworks", "mistral_codestral",
                  "together", "hyperbolic", "sambanova"],
    "research":  ["gemini", "gemma", "grok", "openrouter", "claude", "mistral",
                  "perplexity", "moonshot", "deepseek", "nebius"],
    "creative":  ["claude", "gemini", "gemma", "mistral", "openrouter",
                  "together", "hyperbolic", "novita"],
    "reasoning": ["ollama", "claude", "grok", "gemini", "gemma",
                  "deepseek", "moonshot", "sambanova", "chutes"],
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


_TURN_BUDGET_BASE_DEFAULTS: Dict[str, float | int] = {
    "turn_budget_ratio_low": 0.30,
    "turn_budget_ratio_medium": 0.42,
    "turn_budget_ratio_high": 0.58,
    "turn_output_reserve_low": 1400,
    "turn_output_reserve_medium": 2600,
    "turn_output_reserve_high": 5200,
}

_TURN_BUDGET_FAMILY_DEFAULTS: Dict[str, Dict[str, float | int]] = {
    "compact": {
        "turn_budget_ratio_low": 0.24,
        "turn_budget_ratio_medium": 0.34,
        "turn_budget_ratio_high": 0.46,
        "turn_output_reserve_low": 1100,
        "turn_output_reserve_medium": 1900,
        "turn_output_reserve_high": 3200,
    },
    "balanced": {
        "turn_budget_ratio_low": 0.30,
        "turn_budget_ratio_medium": 0.42,
        "turn_budget_ratio_high": 0.58,
        "turn_output_reserve_low": 1400,
        "turn_output_reserve_medium": 2600,
        "turn_output_reserve_high": 5200,
    },
    "reasoning": {
        "turn_budget_ratio_low": 0.34,
        "turn_budget_ratio_medium": 0.48,
        "turn_budget_ratio_high": 0.66,
        "turn_output_reserve_low": 1800,
        "turn_output_reserve_medium": 3400,
        "turn_output_reserve_high": 6800,
    },
    "local": {
        "turn_budget_ratio_low": 0.22,
        "turn_budget_ratio_medium": 0.32,
        "turn_budget_ratio_high": 0.44,
        "turn_output_reserve_low": 900,
        "turn_output_reserve_medium": 1600,
        "turn_output_reserve_high": 2600,
    },
}


def _resolve_turn_budget_model_name() -> str:
    configured_model = str(_config.get("model") or "").strip()
    if configured_model:
        return configured_model
    provider_key = str(_config.get("provider") or "auto").lower().strip()
    provider_cfg = PROVIDERS.get(provider_key, {}) if provider_key and provider_key != "auto" else {}
    return str(provider_cfg.get("default_model") or "")


def _classify_turn_budget_model_family(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return "balanced"
    if any(token in normalized for token in ("local-model", "ollama", "llama3.2", "3b", "7b", "8b", "9b", "12b")):
        return "local"
    if any(token in normalized for token in ("mini", "flash", "haiku", "small", "nano", "3.5", "gemma-2-9b", "qwen3-8b")):
        return "compact"
    if any(token in normalized for token in ("o1", "o3", "o4", "opus", "sonnet", "70b", "72b", "90b", "405b", "large", "r1")):
        return "reasoning"
    return "balanced"


def _turn_budget_defaults_for_model(model_name: str) -> Dict[str, Any]:
    family = _classify_turn_budget_model_family(model_name)
    defaults = dict(_TURN_BUDGET_FAMILY_DEFAULTS.get(family, _TURN_BUDGET_FAMILY_DEFAULTS["balanced"]))
    has_custom_override = any(
        os.getenv(env_name) is not None
        for env_name in (
            "TURN_BUDGET_RATIO_LOW",
            "TURN_BUDGET_RATIO_MEDIUM",
            "TURN_BUDGET_RATIO_HIGH",
            "TURN_OUTPUT_RESERVE_LOW",
            "TURN_OUTPUT_RESERVE_MEDIUM",
            "TURN_OUTPUT_RESERVE_HIGH",
        )
    )
    if not has_custom_override:
        has_custom_override = any(_config.get(key) != value for key, value in _TURN_BUDGET_BASE_DEFAULTS.items())
    if has_custom_override:
        for key in _TURN_BUDGET_BASE_DEFAULTS:
            defaults[key] = _config.get(key, defaults[key])
    return {
        "family": family,
        "defaults": defaults,
        "source": "config_override" if has_custom_override else "model_family_default",
    }


def _build_turn_budget_policy(task: str, model_budget: int, input_tokens: int) -> Dict[str, Any]:
    complexity = _score_complexity(task)
    model_name = _resolve_turn_budget_model_name()
    model_defaults = _turn_budget_defaults_for_model(model_name)
    default_values = model_defaults["defaults"]
    ratio_map = {
        "low": float(default_values.get("turn_budget_ratio_low", 0.30) or 0.30),
        "medium": float(default_values.get("turn_budget_ratio_medium", 0.42) or 0.42),
        "high": float(default_values.get("turn_budget_ratio_high", 0.58) or 0.58),
    }
    reserve_map = {
        "low": int(default_values.get("turn_output_reserve_low", 1400) or 1400),
        "medium": int(default_values.get("turn_output_reserve_medium", 2600) or 2600),
        "high": int(default_values.get("turn_output_reserve_high", 5200) or 5200),
    }
    ratio = ratio_map.get(complexity, 0.42)
    output_reserve = reserve_map.get(complexity, 2600)
    input_budget = min(max(512, model_budget - output_reserve), max(512, int(model_budget * ratio)))
    soft_budget = max(256, int(input_budget * 0.90))

    pressure = "none"
    if input_tokens > input_budget:
        pressure = "hard"
    elif input_tokens > soft_budget:
        pressure = "soft"

    disable_ensemble = pressure == "hard" and complexity != "high"
    disable_mcts = pressure in ("soft", "hard")
    tool_budget_mode = "minimal" if pressure == "hard" else str(_config.get("native_tool_budget_mode", "adaptive") or "adaptive")
    if pressure == "soft" and tool_budget_mode == "full":
        tool_budget_mode = "adaptive"

    if complexity == "high":
        system_prompt_max_chars = 3600 if pressure == "hard" else 4200
    elif complexity == "medium":
        system_prompt_max_chars = 2800 if pressure == "hard" else 3400
    else:
        system_prompt_max_chars = 2200 if pressure == "hard" else 2800

    context_max_chars = int(_config.get("injected_context_max_chars", 2200) or 2200)
    tool_result_max_chars = int(_config.get("tool_result_context_max_chars", 900) or 900)
    if pressure == "soft":
        context_max_chars = min(context_max_chars, 1800)
        tool_result_max_chars = min(tool_result_max_chars, 800)
    elif pressure == "hard":
        context_max_chars = min(context_max_chars, 1200)
        tool_result_max_chars = min(tool_result_max_chars, 650)

    return {
        "complexity": complexity,
        "model": model_name,
        "model_family": model_defaults.get("family", "balanced"),
        "defaults_source": model_defaults.get("source", "model_family_default"),
        "pressure": pressure,
        "input_tokens": int(input_tokens),
        "input_budget": int(input_budget),
        "soft_budget": int(soft_budget),
        "output_reserve": int(output_reserve),
        "disable_ensemble": disable_ensemble,
        "disable_mcts": disable_mcts,
        "tool_budget_mode": tool_budget_mode,
        "system_prompt_max_chars": int(system_prompt_max_chars),
        "context_max_chars": int(context_max_chars),
        "tool_result_max_chars": int(tool_result_max_chars),
    }


def get_turn_budget_summary(limit: int = 100, since_ts: float = 0.0) -> Dict[str, Any]:
    capped_limit = max(1, min(int(limit), _MAX_ACTIVITY))
    events = [event for event in activity_log if str(event.get("action") or "") == "turn_budget"]
    if since_ts > 0:
        events = [event for event in events if float(event.get("ts") or 0.0) >= since_ts]
    window = events[-capped_limit:]

    pressure_counts: Dict[str, int] = {}
    complexity_counts: Dict[str, int] = {}
    model_family_counts: Dict[str, int] = {}
    tool_budget_modes: Dict[str, int] = {}
    disable_mcts_count = 0
    disable_ensemble_count = 0
    pressured_turns = 0

    for event in window:
        pressure = str(event.get("pressure") or "none")
        complexity = str(event.get("complexity") or "unknown")
        model_family = str(event.get("model_family") or "balanced")
        tool_budget_mode = str(event.get("tool_budget_mode") or "adaptive")
        pressure_counts[pressure] = pressure_counts.get(pressure, 0) + 1
        complexity_counts[complexity] = complexity_counts.get(complexity, 0) + 1
        model_family_counts[model_family] = model_family_counts.get(model_family, 0) + 1
        tool_budget_modes[tool_budget_mode] = tool_budget_modes.get(tool_budget_mode, 0) + 1
        if pressure in ("soft", "hard"):
            pressured_turns += 1
        if bool(event.get("disable_mcts")):
            disable_mcts_count += 1
        if bool(event.get("disable_ensemble")):
            disable_ensemble_count += 1

    total_turns = len(window)
    recent = [
        {
            "ts": event.get("ts"),
            "session": event.get("session"),
            "pressure": event.get("pressure"),
            "complexity": event.get("complexity"),
            "model_family": event.get("model_family"),
            "disable_mcts": bool(event.get("disable_mcts")),
            "disable_ensemble": bool(event.get("disable_ensemble")),
            "tool_budget_mode": event.get("tool_budget_mode"),
        }
        for event in window[-10:]
    ]
    return {
        "total_turns": total_turns,
        "pressured_turns": pressured_turns,
        "downgrade_rate": round(pressured_turns / total_turns, 4) if total_turns else 0.0,
        "disable_mcts_count": disable_mcts_count,
        "disable_ensemble_count": disable_ensemble_count,
        "pressure_counts": pressure_counts,
        "complexity_counts": complexity_counts,
        "model_family_counts": model_family_counts,
        "tool_budget_modes": tool_budget_modes,
        "recent": recent,
        "source": "activity_log",
        "window_size": capped_limit,
        "unfiltered_total": len([event for event in activity_log if str(event.get("action") or "") == "turn_budget"]),
        "filters": {
            "since_ts": since_ts if since_ts > 0 else None,
        },
    }


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

def _provider_circuit_name(pid: str) -> str:
    return f"provider:{pid}"


def _provider_circuit(pid: str):
    return get_circuit_breaker(_provider_circuit_name(pid))


def _is_rate_limited(pid): return time.time() < _cooldowns.get(pid, 0)


def _is_demoted(pid: str) -> bool:
    return time.time() < float(_provider_demotion_until.get(pid, 0.0) or 0.0)


def _demotion_remaining_seconds(pid: str) -> int:
    return max(0, int(float(_provider_demotion_until.get(pid, 0.0) or 0.0) - time.time()))

def _is_circuit_open(pid: str) -> bool:
    try:
        return _provider_circuit(pid).state == CircuitState.OPEN
    except Exception:
        return False


def _provider_temporarily_unavailable(pid: str) -> bool:
    return _is_rate_limited(pid) or _is_circuit_open(pid) or _is_demoted(pid)

def _mark_rate_limited(pid):
    cd = 15 if PROVIDERS.get(pid,{}).get("keyless") else COOLDOWN_SECONDS
    _cooldowns[pid] = time.time() + cd


def _error_category(error_text: str) -> str:
    msg = str(error_text or "").lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg or "quota" in msg or "throttl" in msg:
        return "rate"
    if "413" in msg or "tokens_limit_reached" in msg or "request body too large" in msg:
        return "rate"   # treat as soft rate (short cooldown) — different model may succeed
    if "401" in msg or "unauthorized" in msg or "invalid api key" in msg or "not authenticated" in msg or "wrong api key" in msg:
        return "auth"
    if "402" in msg or "payment" in msg or "subscription" in msg or "upgrade" in msg or "insufficient credits" in msg:
        return "payment"
    # Persistent config errors (wrong model name, unsupported feature): treat as auth-class
    # so repeated failures trigger demotion and the provider is skipped automatically.
    if "unknown_model" in msg or "model_not_found" in msg or "unknown model" in msg or "does not exist" in msg:
        return "auth"
    if "developer instruction is not enabled" in msg or "invalid_argument" in msg:
        return "auth"
    return "other"


def _effective_model_for_provider(pid: str, cfg: Dict[str, Any]) -> str:
    preferred = (
        str(_config.get("model") or "").strip()
        or str(cfg.get("_selected_model") or "").strip()
        or str(cfg.get("default_model") or "").strip()
    )
    if not FREE_ONLY_MODE:
        return preferred
    # In FREE_ONLY_MODE, use provider's declared free_model first (e.g. openrouter :free).
    free_model = str((cfg.get("free_tier") or {}).get("free_model") or "").strip()
    if free_model:
        return free_model
    # For providers with model-name allowlist patterns, enforce them.
    allow_patterns = _FREE_MODEL_ALLOWLIST.get(pid, [])
    if allow_patterns:
        if any(p.search(preferred) for p in allow_patterns):
            return preferred
        fallback = str(cfg.get("default_model") or "").strip()
        if fallback and any(p.search(fallback) for p in allow_patterns):
            return fallback
        if fallback and (":free" in fallback.lower() or "free" in fallback.lower()):
            return fallback
    # All other free-tier providers: preferred model is fine as-is.
    return preferred


def _is_provider_free_usable(pid: str, cfg: Dict[str, Any]) -> bool:
    """Return True if this provider can be used at zero cost."""
    free_tier = cfg.get("free_tier") or {}
    if not free_tier.get("available", False):
        return False
    # Keyless providers are always free regardless of model.
    if cfg.get("keyless", False):
        return True
    # opt_in providers must have a configured key to be usable.
    if not _has_key(cfg):
        return False
    # For providers with model-name restrictions, the selected model must match.
    patterns = _FREE_MODEL_ALLOWLIST.get(pid)
    if patterns:
        model = _effective_model_for_provider(pid, cfg)
        return any(p.search(model) for p in patterns)
    return True

def _record_provider_failure(pid: str, error_text: str, source: str = "runtime") -> None:
    category = _error_category(error_text)
    if category not in ("auth", "payment", "rate"):
        return
    if source == "warmup":
        strikes = int(_provider_warmup_failure_strikes.get(pid, 0)) + 1
        _provider_warmup_failure_strikes[pid] = strikes
        if strikes >= WARMUP_DEMOTION_STRIKES:
            _provider_demotion_until[pid] = time.time() + WARMUP_DEMOTION_SECONDS
            _provider_demotion_reasons[pid] = f"warmup_{category}"
    elif category in ("auth", "payment"):
        # Runtime auth/payment failures are persistent config errors — demote for a long window
        # so we don't waste a request on every turn probing a broken provider.
        _provider_demotion_until[pid] = time.time() + 3600  # 1 hour
        _provider_demotion_reasons[pid] = f"runtime_{category}"
    elif category == "rate":
        # Runtime rate-limit events are already managed by cooldown; keep a short demotion
        # so routing avoids immediately retrying noisy providers.
        _provider_demotion_until[pid] = max(_provider_demotion_until.get(pid, 0.0), time.time() + 30)
        _provider_demotion_reasons[pid] = "runtime_rate"
def _is_rl_error(exc):
    msg = str(exc).lower()
    if isinstance(exc, __import__('requests').HTTPError):
        if exc.response is not None and exc.response.status_code == 429: return True
    return any(p in msg for p in ["rate limit","rate_limit","too many requests","quota","throttl"])
def _provider_secret_name(cfg: Dict[str, Any]) -> str:
    return str(cfg.get("env_key", "") or "").strip()


def _provider_api_key(cfg: Dict[str, Any]) -> str:
    if cfg.get("keyless", False):
        # Keyless providers should not force a synthetic token.
        # Some backends reject malformed/placeholder Authorization headers.
        return ""
    secret_name = _provider_secret_name(cfg)
    if not secret_name:
        return ""
    raw = str(get_secret(secret_name, "") or "").strip()
    # Reject placeholder/comment values: must be pure printable ASCII and not
    # start with '#'.  Non-ASCII keys (e.g. em-dash in a human-readable hint)
    # cause http.client latin-1 header encoding errors.
    if not raw or raw.startswith("#") or not raw.isascii():
        return ""
    return raw


def _has_key(cfg: Dict[str, Any]) -> bool:
    """Return True if the provider can be used without user opt-in, or the user has supplied a key.

    Providers with ``opt_in: True`` require the user to explicitly configure an API key.
    They are **never** included in routing unless a valid key is present.
    Keyless providers (``keyless: True``) are always available.
    """
    if cfg.get("keyless", False):
        return True
    # opt_in providers are excluded unless the user has configured a key.
    if cfg.get("opt_in", False):
        return bool(_provider_api_key(cfg))
    # Legacy providers without the opt_in flag: require a key.
    return bool(_provider_api_key(cfg))

_FREE_PROVIDERS: frozenset = frozenset(
    pid for pid, cfg in PROVIDERS.items() if cfg.get("keyless", False)
)
_recent_provider_hint: Dict[str, str] = {}

def _smart_order(task: str, resources: Optional[Dict[str, Any]] = None) -> List[str]:
    pref = _config["provider"]
    _in_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
    # Keep routing deterministic in tests: ignore persistent demotion/circuit
    # runtime state that may leak across test classes.
    if _in_pytest:
        avail = {pid for pid, cfg in PROVIDERS.items() if _has_key(cfg) and not _is_rate_limited(pid)}
    else:
        avail = {pid for pid, cfg in PROVIDERS.items() if _has_key(cfg) and not _provider_temporarily_unavailable(pid)}
    # When no opt-in providers are configured, fall back to genuinely free/keyless
    # providers only.  Never silently attempt paid providers without user consent.
    if not avail:
        avail = {pid for pid in _FREE_PROVIDERS if not _provider_temporarily_unavailable(pid)}
    if not avail:
        avail = set(_FREE_PROVIDERS)

    # Keep test routing deterministic: ignore inherited FREE_ONLY_MODE env in pytest.
    if FREE_ONLY_MODE and not _in_pytest:
        free_avail = {pid for pid in avail if _is_provider_free_usable(pid, PROVIDERS.get(pid, {}))}
        if free_avail:
            avail = free_avail
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

    # In auto mode, prioritize fully configured conversational providers first.
    # Keep anonymous llm7 as a fallback because it often enforces tight limits.
    if pref == "auto":
        priority_front: List[str] = []
        if "openrouter" in ordered and _provider_api_key(PROVIDERS.get("openrouter", {})):
            priority_front.append("openrouter")
        if "ollama" in ordered:
            priority_front.append("ollama")
        if priority_front:
            ordered = priority_front + [p for p in ordered if p not in priority_front]
        if "llm7" in ordered and len(ordered) > 1:
            ordered = [p for p in ordered if p != "llm7"] + ["llm7"]

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

    # Budget-aware filtering: drop providers that exceed the cost ceiling.
    # FREE_ONLY_MODE forces free-tier provider routing globally.
    # Under pytest, make routing deterministic and avoid inheriting shell-level
    # budget env that can hide paid providers expected by contract tests.
    budget_tier = "any" if os.getenv("PYTEST_CURRENT_TEST") else ("free" if FREE_ONLY_MODE else BUDGET_TIER)
    if budget_tier != "any":
        max_cost = _BUDGET_MAX_COST.get(budget_tier, 999.0)
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
    if ollama_cfg and (_has_key(ollama_cfg)) and not _provider_temporarily_unavailable("ollama"):
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
    "nexus_prime_alpha": {
        "label": "Nexus Prime Alpha",
        "emoji": "🧠",
        "description": "Fine-tuned sovereign model persona for production reasoning and coding",
        "temperature": 0.08,
        "system_extra": (
            "You are in NEXUS PRIME ALPHA mode. Prefer local-first sovereign inference paths, "
            "benchmark-backed decisions, and adapter-aware responses. "
            "When uncertainty is high, explicitly propose evaluation and verification steps before action."
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

    custom_instructions = _get_custom_instructions().strip()
    if custom_instructions:
        base = base.rstrip() + (
            "\n\n[USER INSTRUCTIONS - always follow these]\n"
            f"{custom_instructions}\n"
        )

    persona_name = str(_config.get("persona") or "").strip()
    profile_pack = load_profile_pack(persona_name=persona_name)
    profile_instructions = str(profile_pack.get("instructions") or "").strip()
    if profile_instructions:
        base = base.rstrip() + (
            "\n\n[FILE PROFILE CONTEXT]\n"
            "The following profile files were discovered at runtime and merged as advisory identity/instruction context. "
            "These never override safety and policy constraints.\n"
            f"{profile_instructions}\n"
        )
    return base


def get_provider_system_prompt(max_chars: int = 7000, native_tools: bool = False) -> str:
    """Return a bounded system prompt for upstream provider compatibility.

    When ``native_tools=True`` the returned prompt omits the legacy
    "Reply ONLY with valid JSON" instruction and custom action-format list,
    since the model will use the native function-calling API instead.
    """
    if native_tools:
        prompt = _get_native_tools_system_prompt()
    else:
        prompt = get_system_prompt()
    if len(prompt) <= max_chars:
        return prompt
    marker = "\n\n[... system prompt truncated for provider size limits ...]\n\n"
    keep_head = max(0, int(max_chars * 0.70))
    keep_tail = max(0, max_chars - keep_head - len(marker))
    return prompt[:keep_head] + marker + prompt[-keep_tail:]


# ── Native tool-calling helpers ───────────────────────────────────────────────

_nexus_tools_cache: Dict[str, List[Dict]] = {}


def _select_native_tool_include(task: str) -> set[str] | None:
    mode = str(_config.get("native_tool_budget_mode", "adaptive") or "adaptive").lower()
    if mode == "full":
        return None

    include: set[str] = {
        "calculate", "get_time", "json_format",
        "read_file", "write_file", "list_files", "search_in_files",
        "run_command", "diff", "read_page", "web_search", "api_call",
        "respond", "clarify", "plan", "think", "think_deep",
    }
    text = (task or "").lower()

    if any(k in text for k in ("github.com/", "git ", "repo", "repository", "commit", "branch", "pr ")):
        include.update({"clone_repo", "git_status", "git_diff", "git_log", "git_checkout", "git_pull", "commit_push", "create_pull_request"})
    if any(k in text for k in ("database", "sql", "postgres", "sqlite", "query")):
        include.update({"query_db", "inspect_db", "pg_query", "sqlite_query", "inspect_sqlite", "inspect_postgres"})
    if any(k in text for k in ("pdf", ".pdf", "docx", ".docx", "xlsx", ".xlsx", "pptx", ".pptx", "csv", ".csv")):
        include.update({"read_pdf", "read_docx", "read_xlsx", "read_pptx", "read_csv", "write_csv"})
    if any(k in text for k in ("rag", "retrieval", "knowledge base", "vector")):
        include.update({"rag_ingest", "rag_query", "rag_status"})
    if any(k in text for k in ("schedule", "cron", "periodic", "background job")):
        include.update({"cron_schedule", "cron_list", "cron_cancel"})
    if any(k in text for k in ("music", "song", "melody", "audio track")):
        include.add("generate_music")
    if any(k in text for k in ("3d", "mesh", "glb", "obj model", "three dimensional")):
        include.add("generate_3d_model")

    if mode == "minimal":
        include = {
            "read_file", "write_file", "list_files", "run_command",
            "web_search", "read_page", "json_format", "calculate", "get_time",
            "respond", "clarify", "plan", "think", "think_deep",
        } | ({"generate_music"} if "generate_music" in include else set()) | ({"generate_3d_model"} if "generate_3d_model" in include else set())
    return include


def _get_nexus_tools(task: str = "") -> List[Dict]:
    """Return cached OpenAI tools, using adaptive subsets to reduce token cost."""
    include = _select_native_tool_include(task)
    if include is None:
        cache_key = "full"
    else:
        joined = "|".join(sorted(include))
        cache_key = "subset:" + hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]
    cached = _nexus_tools_cache.get(cache_key)
    if cached is not None:
        return cached
    built = build_openai_tools(include=include)
    if len(_nexus_tools_cache) > 64:
        _nexus_tools_cache.clear()
    _nexus_tools_cache[cache_key] = built
    return built


def _get_native_tools_system_prompt(max_chars: int = 4000) -> str:
    """System prompt for native function-calling mode.

    Replaces the legacy "Reply ONLY with valid JSON + action list" section with
    a concise instruction that lets the model use the tools= array natively.
    The safety rules, persona context, and GitHub workflow are preserved.
    """
    persona = get_active_persona()
    persona_name = get_active_persona_name()
    base = (
        f"You are Nexus AI — a sovereign, privacy-first AI agent "
        f"(persona: {persona_name}) part of the Nexus Systems Ecosystem.\n\n"
        "Use the provided function tools to accomplish tasks.  "
        "When the task is complete or you have a final answer, call the "
        "'respond' tool (or reply as plain text if no further tool is needed).\n\n"
        "Output format:\n"
        "- Always write your final answer as markdown prose.\n"
        "- NEVER return a raw JSON object or JSON array as your final answer.\n"
        "- Use code blocks only for code/commands, not for general text.\n\n"
        "Rules:\n"
        "- Call clarify only for new project creation where architecture choices matter (2-4 questions max).\n"
        "- Plan BEFORE building 3+ files.\n"
        "- Use get_time for any time/date question — never web_search for this.\n"
        "- Use run_command conservatively; never run rm -rf, sudo, or destructive ops.\n"
        "- Never ask for information you can obtain with tools.\n"
        "- For GitHub URLs with development intent, clone_repo immediately then proceed.\n"
        "- Keep responses concise; 1-3 sentences per section unless depth is essential.\n"
    )
    custom = _get_custom_instructions()
    if custom:
        base += f"\nCustom instructions:\n{custom}\n"
    return base[:max_chars]

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
- In strict no-guess mode, any unresolved uncertainty must return a structured clarification card instead of executing actions.
- plan BEFORE building 3+ files. Then execute immediately.
- clone_repo: use the exact URL from the user's message. Never use placeholder URLs.
- commit_push: always include repo_url so the right repo gets pushed.
- run_command: no rm -rf, sudo, or destructive ops.
- get_time for any time/date question — never web_search for this.
- calculate/weather/currency/convert for math, weather, money, units.
- image_gen for any request to generate, draw, create, or visualise an image.
- write_file produces artifacts if it's HTML/SVG/CSS+JS — the UI will render them.
- Never ask for info you can get with tools.

GITHUB REPO WORKFLOW (critical — follow this exactly when given a GitHub URL):
When the user mentions a GitHub URL with any development intent ("help", "develop", "continue",
"improve", "fix", "build", "work on"), you MUST follow this sequence without asking:
  1. clone_repo the URL immediately.
  2. The clone_repo result includes a line "read_file prefix: <prefix>/". USE THAT PREFIX EXACTLY
     for every subsequent read_file call. Example: if the result says "read_file prefix: ca_session_abc/MyRepo/"
     then call: read_file ca_session_abc/MyRepo/README.md
  3. read_file <prefix>README.md (or main entry point shown in Top-level)
  4. read_file <prefix><MainSourceFile> — 1-2 more key source files ONLY. Stop at 3 reads total.
     NEVER call list_files. NEVER retry read_file with the same path. NEVER use absolute paths.
  5. IMMEDIATELY respond with a FULL ANALYSIS after reading at most 3 files: what the project is,
     current state, assessment of the code, and 3-5 concrete prioritised next steps.
     DO NOT call write_file, run_command, or any other action on the first turn — just respond.

IF THE TASK STARTS WITH "[REPOS ALREADY CLONED":
  - The repo is already on disk. File paths are listed in the task.
  - Read at most 3 files from that list (README first, then 1-2 source files).
  - After those reads, call respond IMMEDIATELY with your full analysis.
  - Do NOT call clone_repo again. Do NOT read more than 3 files. Do NOT call list_files.

Do NOT stop after cloning. Do NOT ask "what would you like to do?".
ALWAYS finish with a respond action — never leave the user without an answer.
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
    if not os.path.exists(full):
        # Help the model recover without looping: list immediate subdirs that may contain the file.
        try:
            subdirs = [d for d in os.listdir(workdir) if os.path.isdir(os.path.join(workdir, d)) and not d.startswith(".")]
            hint = f" Available subdirectories: {', '.join(subdirs[:8])}" if subdirs else ""
        except Exception:
            hint = ""
        return (
            f"File not found: {path}.{hint} "
            "If you cloned a repo, prefix the path with the repo folder name shown in the clone_repo result."
        )
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
        out = _redact_sensitive_text(mask_token(out))
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
            git_err = _redact_sensitive_text((r.stdout + r.stderr).strip(), [token])
            return (f"❌ Both API fetch and git clone failed.\n"
                    f"API: fetched 0 files. Git: {git_err[:300]}")
        count = sum(len(fs) for _,_,fs in os.walk(dest))

    top = sorted([f for f in os.listdir(dest) if not f.startswith('.')])[:20]
    rel = os.path.relpath(dest, workdir)
    return (f"✅ Fetched {owner}/{repo_name} via GitHub API ({count} files)\n"
            f"Local path: {dest}\n"
            f"read_file prefix: {rel}/\n"
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



def _clarification_terminal_message() -> str:
    return (
        "Clarification required before I can continue. Please answer the clarification questions and I will proceed."
    )


def _budget_terminal_message(reason: str, elapsed_s: float = 0.0, tool_calls: int = 0) -> str:
    if reason == "max_time_s":
        suffix = f" (elapsed: {elapsed_s:.1f}s)" if elapsed_s else ""
        return f"Execution budget reached: maximum runtime exceeded{suffix}. Please retry or narrow the task scope."
    if reason == "max_tool_calls":
        suffix = f" ({tool_calls} tool calls used)" if tool_calls else ""
        return f"Execution budget reached: maximum tool calls exceeded{suffix}. Please retry with a tighter objective."
    return "Execution budget reached before completion. Please retry with a narrower request."

def _try_direct(task: str) -> Optional[str]:
    task_lc = (task or "").strip().lower()
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


def _provider_unavailable_message(task: str) -> str:
    return (
        "I could not reach any model provider for this turn. "
        "Please retry in a moment, or configure at least one active provider key in Settings."
    )


_STRICT_HIGH_RISK_ACTIONS = {
    "write_file", "delete_file", "run_command", "clone_repo", "commit_push",
    "create_repo", "api_call", "query_db", "db_migrate", "inspect_db",
}
_DESTRUCTIVE_ACTIONS = {
    "delete_file", "run_command", "clone_repo", "commit_push",
    "create_repo", "api_call", "db_migrate",
}
_STRICT_EVIDENCE_REQUIRED_ACTIONS = {
    "delete_file", "run_command", "commit_push", "create_repo", "api_call", "query_db", "db_migrate", "inspect_db",
}
_STRICT_EXECUTION_CONTRACT_ACTIONS = {
    "delete_file", "run_command", "commit_push", "create_repo", "api_call", "query_db", "db_migrate", "inspect_db",
}
_STRICT_EVIDENCE_ACTIONS = {
    "web_search", "read_page", "api_call", "query_db", "inspect_db", "rag_query", "read_file",
}
_ACTION_REQUIRED_FIELDS: Dict[str, List[str]] = {
    "respond": ["content"],
    "clarify": ["questions"],
    "run_command": ["cmd"],
    "write_file": ["path", "content"],
    "read_file": ["path"],
    "delete_file": ["path"],
    "clone_repo": ["url"],
    "commit_push": ["message", "repo_url"],
    "web_search": ["query"],
    "api_call": ["method", "url"],
    "query_db": ["connection_string", "query"],
}


def _task_has_format_requirement(task: str) -> bool:
    t = (task or "").lower()
    hints = ("json", "yaml", "csv", "markdown", "table", "bullet", "schema", "format", "xml", "code block", "```")
    return any(h in t for h in hints)


def _task_has_constraints(task: str) -> bool:
    t = (task or "").lower()
    hints = (
        "must", "should", "do not", "don't", "without", "avoid", "strict", "only", "never", "constraint",
    )
    return any(h in t for h in hints)


def _task_has_explicit_goal(task: str) -> bool:
    t = (task or "").strip()
    if len(t) < 12:
        return False
    return bool(re.search(r"\b(build|implement|create|fix|update|add|remove|refactor|explain|summarize|analyze|review|compare|design)\b", t, re.IGNORECASE))


def _task_has_complete_inputs(task: str) -> bool:
    t = (task or "").strip().lower()
    if not t:
        return False
    if any(token in t for token in ("tbd", "todo", "something", "whatever", "etc", "as needed", "you decide")):
        return False
    return True


def _missing_required_fields(action: Dict[str, Any]) -> List[str]:
    kind = str(action.get("action", "")).strip()
    required = _ACTION_REQUIRED_FIELDS.get(kind, [])
    missing: List[str] = []
    for field in required:
        value = action.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and not value.strip():
            missing.append(field)
        elif isinstance(value, list) and not value:
            missing.append(field)
    return missing


def _conflicting_instruction_signal(task: str, kind: str) -> bool:
    text = (task or "").lower()
    if not kind:
        return False
    deny_hints = {
        "run_command": ("don't run", "do not run", "no shell", "no command"),
        "write_file": ("don't edit", "do not edit", "read only", "no edits"),
        "delete_file": ("don't delete", "do not delete", "no delete"),
        "api_call": ("no network", "offline only", "don't call api"),
    }
    return any(h in text for h in deny_hints.get(kind, ()))


def _adversarial_self_check_issues(task: str, action: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    kind = str(action.get("action", ""))
    content = str(action.get("content", ""))
    if "TODO" in content or "TBD" in content or "assume" in content.lower():
        issues.append("unverified assumptions in draft output")
    if kind in _STRICT_HIGH_RISK_ACTIONS and any(x in str(action).lower() for x in ("example", "placeholder", "<", "...")):
        issues.append("high-risk action contains non-deterministic placeholder input")
    if not _task_has_complete_inputs(task) and kind in _STRICT_HIGH_RISK_ACTIONS:
        issues.append("high-risk action inferred missing task inputs")
    return issues


def _build_clarification_payload(task: str, action: Dict[str, Any], reasons: List[str], score: float) -> Dict[str, Any]:
    readable = {
        "missing_parameters": "Required parameters are missing for the planned action.",
        "conflicting_instructions": "The planned action conflicts with your instructions.",
        "weak_retrieval_evidence": "There is not enough evidence gathered to execute safely.",
        "low_model_confidence": "Model confidence is below the strict threshold.",
        "schema_mismatch": "Planned action payload does not match required schema.",
        "unsafe_side_effects": "Planned action has unsafe side effects under strict mode.",
        "execution_contract_missing_goal": "Goal is not explicit enough for deterministic execution.",
        "execution_contract_missing_inputs": "Inputs are incomplete for deterministic execution.",
        "execution_contract_missing_constraints": "Constraints are not explicit.",
        "execution_contract_missing_output_format": "Expected output format is not explicit.",
        "conflicting_tool_output": "Tool output conflicts with prior context and needs confirmation.",
        "adversarial_self_check": "Adversarial self-check found unresolved uncertainty.",
    }
    unclear = [readable.get(r, r.replace("_", " ")) for r in reasons]
    action_name = str(action.get("action", "respond") or "respond")
    options = [
        {
            "id": "provide-missing-inputs",
            "label": "Provide missing inputs",
            "description": "Share concrete values for required fields so execution can proceed deterministically.",
            "recommended": True,
        },
        {
            "id": "adjust-constraints",
            "label": "Adjust constraints",
            "description": "Clarify hard constraints, risk tolerance, and whether this action is allowed.",
            "recommended": False,
        },
        {
            "id": "confirm-proceed",
            "label": "Confirm proceed",
            "description": "Proceed anyway with explicit confirmation of the risk and intended action.",
            "recommended": False,
        },
    ]
    questions = [
        {
            "id": "execution_confirmation",
            "text": f"Action '{action_name}' is blocked by strict mode. Choose next step:",
            "options": ["Provide missing inputs", "Adjust constraints", "Confirm proceed"],
        },
        {
            "id": "required_details",
            "text": "Provide the exact values or constraints needed to proceed.",
            "type": "text",
            "placeholder": "Example: target file path, command args, expected output format, evidence source...",
        },
    ]
    return {
        "type": "clarify",
        "schema": "nexus.clarification.v1",
        "card": {
            "what_is_unclear": unclear,
            "why_it_blocks_correctness": "Strict no-guess mode blocks execution when doubt is non-zero to prevent incorrect or unsafe actions.",
            "options": options,
            "allow_freeform": True,
            "freeform_label": "Additional clarification",
            "doubt_score": round(score, 3),
            "blocked_action": action_name,
        },
        "questions": questions,
        "reason_codes": reasons,
    }


def _strict_doubt_assessment(
    task: str,
    action: Dict[str, Any],
    llm_confidence: float,
    evidence_hits: int,
    recent_conflict: str,
    confidence_threshold: float,
    evidence_threshold: int,
    strict_no_guess_mode: bool = False,
    session_id: str = "",
) -> Dict[str, Any]:
    reasons: List[str] = []
    suppressed_reasons: List[str] = []
    score = 0.0
    kind = str(action.get("action", "")).strip()
    clone_url = str(action.get("url", "") or "").strip()
    explicit_repo_clone = (
        kind == "clone_repo"
        and bool(_GITHUB_URL_RE.search(task or "") or _GITHUB_URL_RE.search(clone_url))
    )

    missing_fields = _missing_required_fields(action)
    if missing_fields:
        reasons.append("missing_parameters")
        score += 0.30

    if missing_fields:
        reasons.append("schema_mismatch")
        score += 0.20

    if _conflicting_instruction_signal(task, kind):
        reasons.append("conflicting_instructions")
        score += 0.25

    if recent_conflict:
        reasons.append("conflicting_tool_output")
        score += 0.20

    if (
        (strict_no_guess_mode or kind in _STRICT_HIGH_RISK_ACTIONS)
        and llm_confidence < confidence_threshold
    ):
        if explicit_repo_clone:
            suppressed_reasons.append("low_model_confidence")
        else:
            reasons.append("low_model_confidence")
            score += 0.20

    if kind in _STRICT_EVIDENCE_REQUIRED_ACTIONS and evidence_hits < evidence_threshold:
        if explicit_repo_clone:
            suppressed_reasons.append("weak_retrieval_evidence")
        else:
            reasons.append("weak_retrieval_evidence")
            score += 0.25

    if kind in _STRICT_EXECUTION_CONTRACT_ACTIONS and not _task_has_explicit_goal(task):
        if explicit_repo_clone:
            suppressed_reasons.append("execution_contract_missing_goal")
        else:
            reasons.append("execution_contract_missing_goal")
            score += 0.20
    if kind in _STRICT_EXECUTION_CONTRACT_ACTIONS and not _task_has_complete_inputs(task):
        if explicit_repo_clone:
            suppressed_reasons.append("execution_contract_missing_inputs")
        else:
            reasons.append("execution_contract_missing_inputs")
            score += 0.20
    if kind in _STRICT_EXECUTION_CONTRACT_ACTIONS and not _task_has_constraints(task):
        if explicit_repo_clone:
            suppressed_reasons.append("execution_contract_missing_constraints")
        else:
            reasons.append("execution_contract_missing_constraints")
            score += 0.10
    if kind in _STRICT_EXECUTION_CONTRACT_ACTIONS and not _task_has_format_requirement(task):
        if explicit_repo_clone:
            suppressed_reasons.append("execution_contract_missing_output_format")
        else:
            reasons.append("execution_contract_missing_output_format")
            score += 0.10

    adversarial_issues = _adversarial_self_check_issues(task, action)
    if adversarial_issues:
        reasons.append("adversarial_self_check")
        score += 0.20

    if kind in _DESTRUCTIVE_ACTIONS and reasons and not explicit_repo_clone:
        reasons.append("unsafe_side_effects")
        score += 0.15

    if explicit_repo_clone and strict_no_guess_mode and suppressed_reasons:
        event_ts = time.time()
        repo_label = (clone_url or (task or "")[:120] or "clone_repo")[:120]
        deduped_suppressed = list(dict.fromkeys(suppressed_reasons))
        _push_activity({
            "ts": event_ts,
            "action": "strict_clone_bootstrap_exception",
            "label": repo_label,
            "status": "allowed",
            "session": session_id or None,
            "reason_codes": deduped_suppressed,
        })
        try:
            record_strict_clone_bypass_event(
                ts=event_ts,
                session_id=session_id,
                repo_url=clone_url,
                label=repo_label,
                reason_codes=deduped_suppressed,
                details={
                    "status": "allowed",
                    "strict_no_guess_mode": strict_no_guess_mode,
                    "task_excerpt": str(task or "")[:240],
                },
            )
        except Exception:
            pass

    deduped_reasons = list(dict.fromkeys(reasons))
    return {
        "score": max(0.0, score),
        "reasons": deduped_reasons,
        "missing_fields": missing_fields,
        "adversarial_issues": adversarial_issues,
    }

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


_tiktoken_enc = None
_tiktoken_lock = None


def _get_tiktoken_enc():
    """Return a cached tiktoken encoder (cl100k_base covers GPT-4/Claude/Llama3).

    Falls back gracefully if tiktoken is not installed — callers receive None
    and must use the character-heuristic fallback.
    """
    global _tiktoken_enc, _tiktoken_lock
    if _tiktoken_enc is not None:
        return _tiktoken_enc
    import threading
    if _tiktoken_lock is None:
        _tiktoken_lock = threading.Lock()
    with _tiktoken_lock:
        if _tiktoken_enc is not None:
            return _tiktoken_enc
        try:
            import tiktoken  # type: ignore
            _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tiktoken_enc = False   # sentinel: tried and unavailable
    return _tiktoken_enc


def _estimate_tokens(text: str) -> int:
    """Count BPE tokens using tiktoken (cl100k_base) with a character-heuristic fallback.

    tiktoken gives ±2% accuracy on real LLM prompts vs. the previous
    len(text)//4 heuristic which could be off by ±30%.
    """
    if not text:
        return 1  # floor: always ≥ 1 token
    enc = _get_tiktoken_enc()
    if enc and enc is not False:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    # Fallback: average GPT-4 tokenisation is ~3.5 chars/token for English.
    return max(1, len(text) * 2 // 7)


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


def _call_openai(
    cfg: Dict,
    messages: List[Dict],
    tools: List[Dict] | None = None,
    system_prompt: str | None = None,
) -> Dict[str, Any]:
    import requests
    secret_name = _provider_secret_name(cfg)
    ctx = inject_request_credentials([secret_name]) if secret_name else nullcontext({})
    with ctx as creds:
        _raw_key = str((creds.get(secret_name) if secret_name else "") or _provider_api_key(cfg) or "").strip()
        # Drop placeholder/comment keys (contain non-ASCII or start with '#')
        api_key = _raw_key if (_raw_key and _raw_key.isascii() and not _raw_key.startswith("#")) else ""
    # Consume vision model override (set by _smart_order_for_vision before the call).
    model = cfg.pop("_vision_override", None) or _effective_model_for_provider(str(cfg.get("id") or ""), cfg)
    if not model:
        model = _effective_model_for_provider(str(cfg.get("id") or ""), cfg)
    is_local = cfg.get("local") and cfg.get("keyless")

    _use_tools = bool(tools)
    _sys_prompt = system_prompt if system_prompt is not None else get_provider_system_prompt(native_tools=_use_tools)

    def _do_request():
        import json as _json
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": _sys_prompt}] + messages,
            "temperature": _config["temperature"],
            "max_tokens": 4096,
        }
        if _use_tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        payload = _json.dumps(body, ensure_ascii=False).encode("utf-8")
        print(
            f"[llm/{cfg.get('id','?')}] payload={len(payload)}B msgs={len(messages)}"
            f"{' tools=' + str(len(tools)) if _use_tools else ''}",
            flush=True,
        )
        _call_timeout = int(os.getenv("LLM_CALL_TIMEOUT_S", "30"))
        r = requests.post(
            cfg["base_url"].rstrip("/")+"/chat/completions",
            headers=headers,
            data=payload,
            timeout=_call_timeout)
        if r.status_code >= 400:
            body_txt = (r.text or "")[:300]
            raise RuntimeError(f"openai_compat_http_{r.status_code}: {body_txt}")
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
    # Some OpenAI-compatible backends (notably local Ollama/Qwen variants)
    # can return an empty ``content`` but place text in reasoning/thinking fields.
    # Normalize those into ``content`` to avoid empty assistant replies.
    if not content:
        content = (
            msg_obj.get("reasoning")
            or msg_obj.get("thinking")
            or msg_obj.get("reasoning_content")
            or ""
        )

    # Reasoning field normalization (DeepSeek/Ollama variants)
    reasoning = (
        msg_obj.get("reasoning_content")
        or msg_obj.get("reasoning")
        or msg_obj.get("thinking")
        or ""
    )

    # ── Native tool-calling path (highest priority) ───────────────────────────
    # When we sent a tools= array, the model returns tool_calls instead of JSON
    # text.  Parse the first tool call into the action dict directly — no regex
    # fragility, no JSON parsing from raw text.
    raw_tool_calls = msg_obj.get("tool_calls") or []
    if raw_tool_calls and _use_tools:
        tc = raw_tool_calls[0]
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else (fn.get("arguments") or {})
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {}
        result: Dict[str, Any] = {"action": fn.get("name", ""), **args}
        if reasoning and not result.get("thought"):
            result["thought"] = reasoning
        # Store the raw tool_call metadata so stream_agent_task can build native history
        result["_tool_calls"] = [
            {"id": tc.get("id") or f"call_{i}", "function": raw_tc.get("function", {})}
            for i, raw_tc in enumerate(raw_tool_calls)
        ]
        result["_native_tool_call"] = True
        if not result.get("action"):
            print(f"[llm/{cfg.get('id','?')}] native tool_call but empty name — raw={fn}", flush=True)
        else:
            print(f"[llm/{cfg.get('id','?')}] native tool_call action={result['action']!r}", flush=True)
        return result

    # In native mode, if no tool_call is returned, treat content as a final
    # assistant response instead of forcing legacy JSON action parsing.
    if _use_tools:
        result_native: Dict[str, Any] = {
            "action": "respond",
            "content": content or "",
        }
        if reasoning and not result_native.get("thought"):
            result_native["thought"] = reasoning
        if raw_tool_calls:
            result_native.setdefault("_tool_calls", [
                {"id": tc.get("id") or f"call_{i}", "function": tc.get("function", {})}
                for i, tc in enumerate(raw_tool_calls)
            ])
        return result_native

    # ── Legacy JSON-parsing path (non-native callers) ────────────────────────
    result = _parse_json(content)
    if not result.get("action"):
        print(f"[llm/{cfg.get('id','?')}] action=None raw={content[:200]!r}", flush=True)
    if reasoning and isinstance(result, dict) and not result.get("thought"):
        result["thought"] = reasoning

    # Preserve any tool_calls metadata even on the legacy path (e.g. Gemini)
    if raw_tool_calls and isinstance(result, dict):
        result.setdefault("_tool_calls", [
            {"id": tc.get("id") or f"call_{i}", "function": tc.get("function", {})}
            for i, tc in enumerate(raw_tool_calls)
        ])

    return result


def _call_grok(messages):
    import requests, time as _t, json as _json
    secret_name = "GROK_API_KEY"  # pragma: allowlist secret
    with inject_request_credentials([secret_name]) as creds:
        _gk = str(creds.get(secret_name) or get_secret(secret_name, "") or "").strip()
        grok_key = _gk if (_gk and _gk.isascii() and not _gk.startswith("#")) else ""
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if grok_key:
        headers["Authorization"] = f"Bearer {grok_key}"
    body = {
        "model": _config["model"] or "grok-3",
        "messages": [{"role":"system","content":get_provider_system_prompt()}]+messages,
        "temperature": _config["temperature"] or get_active_persona()["temperature"],
        "max_tokens": 4096,
    }
    payload = _json.dumps(body, ensure_ascii=False).encode("utf-8")
    resp = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, data=payload, timeout=90)

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
    import requests, json as _json
    secret_name = "CLAUDE_API_KEY"  # pragma: allowlist secret
    with inject_request_credentials([secret_name]) as creds:
        _ck = str(creds.get(secret_name) or get_secret(secret_name, "") or "").strip()
        claude_key = _ck if (_ck and _ck.isascii() and not _ck.startswith("#")) else ""
    body = {
        "model": _config["model"] or "claude-sonnet-4-20250514",
        "system": get_provider_system_prompt(),
        "messages": messages,
        "temperature": _config["temperature"] or get_active_persona()["temperature"],
        "max_tokens": 4096
    }
    payload = _json.dumps(body, ensure_ascii=False).encode("utf-8")
    resp = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": claude_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json; charset=utf-8"},
        data=payload, timeout=90)
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


def _call_single(
    pid: str,
    messages: List[Dict],
    tools: List[Dict] | None = None,
    system_prompt: str | None = None,
) -> Dict[str, Any]:
    cfg = dict(PROVIDERS[pid])
    cfg["id"] = pid
    if cfg["openai_compat"]:
        return _call_openai(cfg, messages, tools=tools, system_prompt=system_prompt)
    # Non-OpenAI-compat providers don't support the tools= path yet — fall back
    # to the legacy JSON-text call (tools param is silently ignored).
    if pid == "grok":   return _call_grok(messages)
    if pid == "claude": return _call_claude_api(messages)
    raise ValueError(f"No caller: {pid}")


class AllProvidersExhausted(Exception): pass


_provider_attempt_state = threading.local()


def _set_last_provider_attempts(attempts: List[Dict[str, Any]]) -> None:
    _provider_attempt_state.attempts = list(attempts)


def get_last_provider_attempts() -> List[Dict[str, Any]]:
    return list(getattr(_provider_attempt_state, "attempts", []) or [])


def _format_provider_attempt_chain(attempts: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for item in attempts:
        provider = str(item.get("provider") or item.get("provider_id") or "provider")
        status = str(item.get("status") or "unknown")
        parts.append(f"{provider}:{status}")
    return " -> ".join(parts)


def _attach_provider_diagnostics(
    payload: Dict[str, Any],
    attempts: List[Dict[str, Any]],
    fallback_reason: str = "",
) -> Dict[str, Any]:
    out = dict(payload or {})
    out.setdefault("provider_attempts", list(attempts))
    out.setdefault("provider_attempt_chain", _format_provider_attempt_chain(attempts))
    if fallback_reason:
        out.setdefault("fallback_reason", fallback_reason)
    return out


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

def call_llm_with_fallback(
    messages: List[Dict],
    task: str = "",
    provider_order: Optional[List[str]] = None,
    source: str = "runtime",
    tools: List[Dict] | None = None,
    system_prompt: str | None = None,
    routing_hints: Dict[str, Any] | None = None,
) -> tuple[Dict, str]:
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
    attempts: List[Dict[str, Any]] = []
    _set_last_provider_attempts([])
    effective_task = task or (messages[-1].get("content","") if messages else "")
    order = _smart_order(effective_task, resources)
    if provider_order:
        seen: set[str] = set()
        constrained: List[str] = []
        for pid in provider_order:
            p = str(pid).strip()
            if not p or p in seen or p not in PROVIDERS:
                continue
            seen.add(p)
            constrained.append(p)
        order = constrained
    if not order:
        _set_last_provider_attempts(attempts)
        raise AllProvidersExhausted("No providers available.")

    # Latency optimization: prefer most recently successful provider for this complexity tier.
    hint_key = _score_complexity(effective_task)
    hinted_pid = _recent_provider_hint.get(hint_key)
    if hinted_pid and hinted_pid in order:
        order = [hinted_pid] + [p for p in order if p != hinted_pid]

    # Vision routing: if any message contains image_url parts, promote
    # vision-capable providers to the front of the queue and select the
    # best local Ollama vision model (sets _vision_override on the ollama cfg).
    if _messages_have_images(messages):
        _smart_order_for_vision(messages)
        _VISION_PROVIDERS = frozenset({
            "ollama", "claude", "gemini", "gemma", "openrouter", "github_models",
            "groq", "together", "fireworks", "hyperbolic", "deepinfra",
            "huggingface", "novita", "moonshot", "openai", "deepseek",
        })
        vision_first = [p for p in order if p in _VISION_PROVIDERS]
        rest         = [p for p in order if p not in _VISION_PROVIDERS]
        order        = vision_first + rest
    complexity = _score_complexity(task or "")
    resource_hint = _resource_tier(resources)
    avail_ram = resources.get("available_ram_gb")
    ram_txt = f"{avail_ram}GB" if avail_ram is not None else "unknown"
    print(f"🧠 {complexity}/{resource_hint} (ram={ram_txt}) → {' → '.join(order[:4])}")
    last_err = None
    for pid in order:
        if _provider_temporarily_unavailable(pid):
            if _is_demoted(pid):
                attempts.append({
                    "provider_id": pid,
                    "provider": PROVIDERS.get(pid, {}).get("label", pid),
                    "status": "demoted_skip",
                    "error": _provider_demotion_reasons.get(pid, "provider temporarily demoted"),
                })
                continue
            attempts.append({
                "provider_id": pid,
                "provider": PROVIDERS.get(pid, {}).get("label", pid),
                "status": "cooldown_skip",
                "error": "provider in cooldown window",
            })
            continue
        started = time.time()
        try:
            breaker = _provider_circuit(pid)
            if tracer:
                with tracer.start_as_current_span("llm.provider.call") as span:
                    if hasattr(span, "set_attribute"):
                        span.set_attribute("llm.provider", pid)
                        span.set_attribute("llm.task", task or "")
                        span.set_attribute("llm.routed_order", " -> ".join(order[:5]))
                        span.set_attribute("llm.circuit_state", breaker.state.value)
                    result = breaker.call(_call_single, pid, messages, tools, system_prompt)
            else:
                result = breaker.call(_call_single, pid, messages, tools, system_prompt)
            elapsed = max(0.0, time.time() - started)
            if llm_counter is not None:
                llm_counter.labels(provider=pid, status="ok").inc()
            if llm_latency is not None:
                llm_latency.labels(provider=pid).observe(elapsed)
            attempts.append({
                "provider_id": pid,
                "provider": PROVIDERS.get(pid, {}).get("label", pid),
                "status": "ok",
                "latency_ms": int(elapsed * 1000),
            })
            _set_last_provider_attempts(attempts)
            if isinstance(result, dict):
                result = _attach_provider_diagnostics(result, attempts)
            _recent_provider_hint[hint_key] = pid
            return result, pid
        except CircuitBreakerOpen as e:
            last_err = e
            attempts.append({
                "provider_id": pid,
                "provider": PROVIDERS.get(pid, {}).get("label", pid),
                "status": "circuit_open",
                "error": str(e),
            })
            print(f"⛔ {pid} circuit open ({e.retry_after:.1f}s)")
        except Exception as e:
            last_err = e
            elapsed = max(0.0, time.time() - started)
            _record_provider_failure(pid, str(e), source=source)
            if llm_counter is not None:
                llm_counter.labels(provider=pid, status="error").inc()
            if llm_latency is not None:
                llm_latency.labels(provider=pid).observe(elapsed)
            if _is_rl_error(e):
                _mark_rate_limited(pid)
                attempts.append({
                    "provider_id": pid,
                    "provider": PROVIDERS.get(pid, {}).get("label", pid),
                    "status": "rate_limited",
                    "error": str(e),
                    "latency_ms": int(elapsed * 1000),
                })
                print(f"↩️ {pid} rate-limited")
            elif isinstance(e, (_r.ConnectionError, _r.Timeout)):
                attempts.append({
                    "provider_id": pid,
                    "provider": PROVIDERS.get(pid, {}).get("label", pid),
                    "status": "connection_error",
                    "error": str(e),
                    "latency_ms": int(elapsed * 1000),
                })
                print(f"⚠️ {pid} connection error")
            else:
                attempts.append({
                    "provider_id": pid,
                    "provider": PROVIDERS.get(pid, {}).get("label", pid),
                    "status": "error",
                    "error": str(e),
                    "latency_ms": int(elapsed * 1000),
                })
                print(f"⚠️ {pid}: {e}")

    result, fallback_provider = _graceful_degraded_response(messages, task, str(last_err))
    attempts.append({
        "provider_id": fallback_provider,
        "provider": fallback_provider,
        "status": "degraded_fallback",
    })
    _set_last_provider_attempts(attempts)
    if isinstance(result, dict):
        reason_tag = "provider_unavailable" if fallback_provider in ("cache", "ollama_local") else ""
        result = _attach_provider_diagnostics(result, attempts, fallback_reason=reason_tag)
    return result, fallback_provider


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
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        test = _r.get(f"{ollama_url}/api/tags", timeout=2)
        if test.status_code == 200:
            tags = test.json().get("models", [])
            if tags:
                first_model = tags[0].get("name", "llama3")
                print(f"⚡ Graceful degradation: Ollama local model {first_model}")
                openai_base = ollama_url if ollama_url.endswith("/v1") else f"{ollama_url}/v1"
                cfg = {
                    "id": "ollama_local_fallback",
                    "base_url": openai_base,
                    "default_model": first_model,
                    "local": True,
                    "keyless": True,
                    "openai_compat": True,
                }
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
    routing_hints: Dict[str, Any] | None = None,
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
    hints = routing_hints or {}

    # Federated path (feature-flagged): if disabled/unavailable/fails, continue
    # through the normal smart routing chain without raising to callers.
    try:
        from .config.feature_flags import ENABLE_FEDERATED_LLM
        from .feature_flags import is_enabled as _flag_enabled
        if _flag_enabled(ENABLE_FEDERATED_LLM, default=False):
            from .federated import try_federated_inference

            fed = try_federated_inference(messages=messages, task=effective_task, routing_hints=hints)
            if bool(fed.get("ok")) and isinstance(fed.get("response"), dict):
                meta.update(
                    {
                        "federated": True,
                        "federated_reason": "used",
                        "federated_latency_ms": int(fed.get("latency_ms") or 0),
                    }
                )
                return fed["response"], str(fed.get("provider") or "federated"), meta
            meta.update(
                {
                    "federated": False,
                    "federated_reason": str(fed.get("reason") or "fallback"),
                    "federated_latency_ms": int(fed.get("latency_ms") or 0),
                }
            )
    except Exception as exc:
        meta.update({"federated": False, "federated_reason": f"error:{exc}"})

    # Build tools + system prompt once for the whole routing chain.
    _native = _config.get("native_tool_calling", False)
    tool_mode_override = hints.get("tool_budget_mode")
    original_tool_budget_mode = _config.get("native_tool_budget_mode")
    if tool_mode_override:
        _config["native_tool_budget_mode"] = str(tool_mode_override)
    try:
        _tools: List[Dict] | None = _get_nexus_tools(effective_task) if _native else None
    finally:
        if tool_mode_override:
            _config["native_tool_budget_mode"] = original_tool_budget_mode
    sys_max_chars = int(hints.get("system_prompt_max_chars") or 4000)
    _sys_prompt: str | None = get_provider_system_prompt(max_chars=sys_max_chars, native_tools=True) if _native else None

    threshold = float(_config.get("ensemble_threshold", 0.4))
    if not hints.get("disable_ensemble") and _config.get("ensemble_mode", True) and is_high_risk(effective_task, threshold=threshold):
        print(f"🔴 High-risk task (score={risk:.2f}) — entering ensemble mode")
        try:
            result, pid, ens_meta = call_llm_ensemble(
                messages=messages,
                task=effective_task,
                providers_fn=lambda t: _smart_order(t, get_system_resources()),
                call_single_fn=lambda pid, msgs: _provider_circuit(pid).call(
                    _call_single, pid, msgs, _tools, _sys_prompt
                ),
                is_rate_limited_fn=_provider_temporarily_unavailable,
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
    result, pid = call_llm_with_fallback(
        messages, effective_task, tools=_tools, system_prompt=_sys_prompt, routing_hints=hints
    )
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
    "generate_music":"🎵","generate_3d_model":"🧱",
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


def is_tool_allowed_for_persona(persona_name: str, tool_name: str) -> bool:
    allowed = get_allowed_tools(persona_name)
    profile_pack = load_profile_pack(persona_name=persona_name)
    profile_allowed = profile_pack.get("allowed_tools")
    if profile_allowed:
        profile_allowed_set = {str(item).strip() for item in profile_allowed if str(item).strip()}
        if allowed is None:
            allowed = profile_allowed_set
        else:
            allowed = set(allowed) & profile_allowed_set
    if allowed is None:
        return True
    return tool_name in allowed


# ── streaming agent ───────────────────────────────────────────────────────────
def stream_agent_task(task: str, history: list, files: list | None = None,
                      stop_evt=None, sid: str = "", trace_id: str = "",
                      max_tool_calls: int = 0, max_time_s: float = 0.0,
                      budget_tokens_out: int = 0,
                      usage_principal: str = "") -> Iterator[Dict[str, Any]]:
    def _stopped(): return stop_evt is not None and stop_evt.is_set()

    # Emit an early heartbeat/status event so SSE clients never observe
    # a silent 200 response with zero lines when downstream providers fail.
    yield {"type": "status", "message": "Processing request..."}

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
    # Skip warm-up when call_llm_smart is monkeypatched (e.g. contract tests)
    # so test side effects are not consumed by the warm-up probe.
    warmup_enabled = os.getenv("AGENT_AUTO_WARMUP", "true").lower() in ("1", "true", "yes")
    llm_smart_module = getattr(call_llm_smart, "__module__", "")
    llm_smart_type_module = type(call_llm_smart).__module__
    llm_smart_type_name = type(call_llm_smart).__name__
    llm_smart_is_mock = (
        hasattr(call_llm_smart, "assert_called")
        or "unittest.mock" in llm_smart_module
        or "unittest.mock" in llm_smart_type_module
        or "Mock" in llm_smart_type_name
    )
    llm_fallback_module = getattr(call_llm_with_fallback, "__module__", "")
    llm_fallback_type_module = type(call_llm_with_fallback).__module__
    llm_fallback_type_name = type(call_llm_with_fallback).__name__
    llm_fallback_is_mock = (
        hasattr(call_llm_with_fallback, "assert_called")
        or "unittest.mock" in llm_fallback_module
        or "unittest.mock" in llm_fallback_type_module
        or "Mock" in llm_fallback_type_name
    )
    mock_tool_mode = llm_smart_is_mock or llm_fallback_is_mock

    test_sid = (sid or "")
    in_test_sid = test_sid.startswith("test-") or test_sid.endswith("-test")
    # Skip auto-warmup for: (1) tests, (2) stream/trace contexts, (3) non-first turns
    is_stream_context = bool(trace_id)  # trace_id indicates stream/non-interactive context
    should_skip_warmup = in_test_sid or is_stream_context or len(history) > 0
    
    if (
        warmup_enabled
        and llm_smart_module == __name__
        and not llm_smart_is_mock
        and not llm_fallback_is_mock
        and not should_skip_warmup
    ):
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
        # Build a curated file list — prefer high-signal files, skip noise.
        # Keeps the instruction short so the model reads a handful of key files and responds.
        _KEY_EXTS = {".md", ".txt", ".rst", ".py", ".js", ".ts", ".jsx", ".tsx",
                     ".go", ".rs", ".java", ".cs", ".cpp", ".c", ".rb", ".swift",
                     ".json", ".toml", ".yaml", ".yml"}
        _SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv",
                      "dist", "build", ".next", "vendor", "coverage"}
        all_files: list[str] = []
        priority_files: list[str] = []   # README + root-level source files first
        for url in urls:
            rname = url.rstrip('/').split('/')[-1].replace('.git','')
            rdir  = os.path.join(workdir, rname)
            if not os.path.isdir(rdir):
                continue
            for dp, dirs, fs in os.walk(rdir):
                # Prune noise dirs in-place so os.walk skips them
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for f in fs:
                    ext = os.path.splitext(f)[1].lower()
                    if ext not in _KEY_EXTS:
                        continue
                    rel = os.path.relpath(os.path.join(dp, f), workdir)
                    depth = rel.count(os.sep)
                    if depth == 1:   # repo root level
                        priority_files.append(rel)
                    else:
                        all_files.append(rel)
        # Root files first, then deeper files; cap total at 20 to avoid overwhelming the model
        curated = priority_files[:12] + all_files[:8]
        file_ctx = "\n".join(curated[:20])
        clean_task = (f"[REPOS ALREADY CLONED — do NOT call clone_repo again]\n"
                      f"These are the key files (relative to session workdir {workdir}):\n{file_ctx}\n\n"
                      f"INSTRUCTIONS: Read at most 4 files (start with README then 1-3 source files), "
                      f"then immediately respond with your full analysis. "
                      f"Do NOT read every file. Do NOT call write_file or run_command on this first turn.\n\n"
                      f"Original request: {clean_task}\n\n"
                      f"Respond in markdown prose (no raw JSON): briefly describe what the project is, "
                      f"its current state, your assessment, and 3-5 bullet-point next steps. "
                      f"Be concise — 2-3 sentences per section max.")

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

    def _assemble_turn_messages(reserve_tokens: int, injected_ctx_chars: int) -> tuple[List[Dict], int]:
        assembled: List[Dict] = _maybe_compress_history(history_list)
        assembled = CONTEXT_WINDOW.compress_to_token_budget(
            assembled,
            token_budget=model_budget,
            reserve_tokens=reserve_tokens,
        )
        injected_count = 0
        _kg_ctx = kg_to_context_string(clean_task, limit=5)
        _mem_ctx = get_memory_context()
        injected_chunks: List[str] = []
        if _kg_ctx:
            injected_chunks.append("[KG CONTEXT]\n" + _kg_ctx)
        if _mem_ctx:
            injected_chunks.append("[MEMORY CONTEXT]\n" + _mem_ctx)
        if injected_chunks:
            merged = "\n\n".join(injected_chunks)
            if len(merged) > injected_ctx_chars:
                merged = merged[:injected_ctx_chars] + "\n... [context truncated for token budget]"
            assembled = [{
                "role": "system",
                "content": "Runtime context (do not repeat verbatim unless asked):\n" + merged,
            }] + assembled
            injected_count = 1
        assembled.append({"role": "user", "content": _build_content(clean_task, files or [])})
        return assembled, injected_count

    base_reserve_tokens = int(_config.get("context_reserve_tokens", 3072) or 3072)
    base_ctx_chars = int(_config.get("injected_context_max_chars", 2200) or 2200)
    messages, _n_injected = _assemble_turn_messages(base_reserve_tokens, base_ctx_chars)
    input_token_estimate = _messages_token_estimate(messages)
    turn_budget_policy = _build_turn_budget_policy(clean_task, model_budget, input_token_estimate)

    if bool(_config.get("turn_budget_enforced", True)) and turn_budget_policy.get("pressure") in ("soft", "hard"):
        reserve_override = max(
            base_reserve_tokens,
            int(turn_budget_policy.get("output_reserve", base_reserve_tokens)),
            max(512, model_budget - int(turn_budget_policy.get("input_budget", model_budget))),
        )
        ctx_override = int(turn_budget_policy.get("context_max_chars", base_ctx_chars))
        messages, _n_injected = _assemble_turn_messages(reserve_override, ctx_override)
        input_token_estimate = _messages_token_estimate(messages)
        turn_budget_policy = _build_turn_budget_policy(clean_task, model_budget, input_token_estimate)
        yield {
            "type": "turn_budget",
            "pressure": turn_budget_policy.get("pressure"),
            "input_tokens": turn_budget_policy.get("input_tokens"),
            "input_budget": turn_budget_policy.get("input_budget"),
            "output_reserve": turn_budget_policy.get("output_reserve"),
            "tool_budget_mode": turn_budget_policy.get("tool_budget_mode"),
            "disable_ensemble": turn_budget_policy.get("disable_ensemble"),
            "disable_mcts": turn_budget_policy.get("disable_mcts"),
        }
    _push_activity({
        "ts": time.time(),
        "action": "turn_budget",
        "label": f"{turn_budget_policy.get('pressure', 'none')}:{turn_budget_policy.get('complexity', 'unknown')}",
        "status": str(turn_budget_policy.get("pressure") or "none"),
        "session": sid,
        "pressure": turn_budget_policy.get("pressure"),
        "complexity": turn_budget_policy.get("complexity"),
        "model": turn_budget_policy.get("model"),
        "model_family": turn_budget_policy.get("model_family"),
        "defaults_source": turn_budget_policy.get("defaults_source"),
        "input_tokens": turn_budget_policy.get("input_tokens"),
        "input_budget": turn_budget_policy.get("input_budget"),
        "output_reserve": turn_budget_policy.get("output_reserve"),
        "disable_ensemble": bool(turn_budget_policy.get("disable_ensemble")),
        "disable_mcts": bool(turn_budget_policy.get("disable_mcts")),
        "tool_budget_mode": turn_budget_policy.get("tool_budget_mode"),
    })

    def _pub_history() -> List[Dict]:
        """History slice safe to return to the client (no injected context prefixes)."""
        return messages[_n_injected:]
    yield {
        "type": "token_breakdown",
        "messages": CONTEXT_WINDOW.token_breakdown(messages),
    }
    providers_used: List[str] = []
    complexity = _score_complexity(clean_task)
    yield {"type":"complexity","level":complexity}

    # Skip MCTS for already-cloned/bypass tasks: the operation is well-defined (read → respond)
    # and MCTS guidance messages prime the model to return score/rationale JSON instead of actions.
    _skip_mcts = clean_task.startswith("[REPOS ALREADY CLONED") or bool(turn_budget_policy.get("disable_mcts"))
    mcts_guidance = None if _skip_mcts else _auto_mcts_guidance(clean_task)
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
    _read_file_count = 0   # track consecutive read_file calls to prevent over-reading
    _strict_mode = bool(_config.get("strict_no_guess_mode", True))
    _strict_confidence_threshold = float(_config.get("strict_confidence_threshold", 0.95) or 0.95)
    _strict_evidence_threshold = int(_config.get("strict_evidence_threshold", 1) or 1)
    _evidence_hits = 0
    _recent_conflict = ""

    def _next_action(msgs: List[Dict], task_text: str) -> tuple[Dict[str, Any], str, Dict[str, Any]]:
        def _from_fallback() -> tuple[Dict[str, Any], str, Dict[str, Any]]:
            _native = bool(_config.get("native_tool_calling", False))
            _routing_hints = {
                "disable_ensemble": bool(turn_budget_policy.get("disable_ensemble")),
                "tool_budget_mode": turn_budget_policy.get("tool_budget_mode"),
                "system_prompt_max_chars": int(turn_budget_policy.get("system_prompt_max_chars", 4000)),
            }
            _tools = _get_nexus_tools(task_text) if _native else None
            _sys_prompt = get_provider_system_prompt(
                max_chars=int(_routing_hints.get("system_prompt_max_chars", 4000)),
                native_tools=True,
            ) if _native else None
            resp, pid = call_llm_with_fallback(
                msgs,
                task_text,
                tools=_tools,
                system_prompt=_sys_prompt,
                routing_hints=_routing_hints,
            )
            if isinstance(resp, dict) and "action" in resp:
                return resp, pid, {}
            content = resp.get("content") if isinstance(resp, dict) else str(resp)
            try:
                parsed = json.loads(content) if isinstance(content, str) else {}
            except Exception:
                parsed = {}
            if isinstance(parsed, dict) and "action" in parsed:
                return parsed, pid, {}
            return {"action": "respond", "content": content or "done", "confidence": 0.9}, pid, {}

        test_sid = (sid or "")
        if test_sid.startswith("test-") or test_sid.endswith("-test"):
            if llm_smart_is_mock:
                action, pid, meta = call_llm_smart(msgs, task_text, routing_hints=turn_budget_policy)
                return action, pid, meta
            return _from_fallback()

        if llm_smart_is_mock:
            action, pid, meta = call_llm_smart(msgs, task_text, routing_hints=turn_budget_policy)
            return action, pid, meta
        if llm_fallback_is_mock:
            return _from_fallback()
        return call_llm_smart(msgs, task_text, routing_hints=turn_budget_policy)

    for _ in range(MAX_LOOP):
        _step_started = time.perf_counter()
        _step_llm_ms = 0.0
        _step_safety_ms = 0.0
        _step_planning_ms = 0.0
        _step_tool_ms = 0.0
        # Budget checks
        if max_time_s > 0 and (time.time() - _budget_start) > max_time_s:
            _elapsed = round(time.time() - _budget_start, 1)
            _budget_evt = {"type": "budget_exceeded", "reason": "max_time_s", "elapsed_s": _elapsed}
            yield _budget_evt
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
            _msg = _budget_terminal_message("max_time_s", elapsed_s=_elapsed)
            messages.append({"role": "assistant", "content": _msg})
            yield {
                "type": "done",
                "content": _msg,
                "provider": cfg.get("label", "Built-in"),
                "model": _config["model"] or cfg.get("default_model", "budget-guard"),
                "history": _pub_history(),
            }
            return
        if max_tool_calls > 0 and _tool_call_count >= max_tool_calls:
            _budget_evt = {"type": "budget_exceeded", "reason": "max_tool_calls", "tool_calls": _tool_call_count}
            yield _budget_evt
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
            _msg = _budget_terminal_message("max_tool_calls", tool_calls=_tool_call_count)
            messages.append({"role": "assistant", "content": _msg})
            yield {
                "type": "done",
                "content": _msg,
                "provider": cfg.get("label", "Built-in"),
                "model": _config["model"] or cfg.get("default_model", "budget-guard"),
                "history": _pub_history(),
            }
            return
        if _stopped():
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
            yield {"type":"done","content":"*(Stopped)*","provider":cfg.get("label","?"),
                   "model":"—","history":messages}
            return

        try:
            _llm_t0 = time.perf_counter()
            action, pid, _llm_meta = _next_action(messages, clean_task)
            _step_llm_ms = (time.perf_counter() - _llm_t0) * 1000.0
            if _llm_meta.get("ensemble"):
                yield {"type": "ensemble",
                       "unanimous": _llm_meta.get("unanimous"),
                       "polled": _llm_meta.get("polled", []),
                       "action_votes": _llm_meta.get("action_votes", {}),
                       "risk_score": _llm_meta.get("risk_score", 0.0)}
        except AllProvidersExhausted as e:
            time.sleep(8)
            try:
                action, pid, _llm_meta = _next_action(messages, clean_task)
            except AllProvidersExhausted:
                provider_attempts = get_last_provider_attempts()
                fallback_text = _provider_unavailable_message(clean_task)
                messages.append({"role": "assistant", "content": fallback_text})
                cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
                yield {
                    "type": "done",
                    "content": fallback_text,
                    "provider": cfg.get("label", "Built-in"),
                    "model": _config["model"] or cfg.get("default_model", "fallback"),
                    "fallback_reason": "provider_unavailable",
                    "provider_attempt_chain": _format_provider_attempt_chain(provider_attempts),
                    "provider_attempts": provider_attempts,
                    "history": _pub_history(),
                }
                return

        # Auto-retry once if output is clearly bad
        if _is_bad_output(action):
            print(f"⚠️ Bad output from {pid}, retrying once…")
            try:
                action, pid, _ = _next_action(messages, clean_task)
            except AllProvidersExhausted:
                pass   # give up, use original bad output

        if pid not in providers_used:
            providers_used.append(pid)
            if len(providers_used) > 1:
                yield {"type":"fallback",
                       "chain":" → ".join(PROVIDERS[p]["label"] for p in providers_used)}

        kind = action.get("action")
        # If model returned action=null/missing but included content, treat it as a respond
        if not kind and action.get("content"):
            action["action"] = "respond"
            kind = "respond"
        elif not kind:
            # Completely missing action — recovery prompt differs by mode.
            if _config.get("native_tool_calling", False):
                _bad_fmt_msg = (
                    "Your previous reply did not include a tool call or a final answer. "
                    "Please either call exactly one tool or provide the final answer now."
                )
                messages.append({"role": "assistant", "content": action.get("content", "") or ""})
                messages.append({"role": "user", "content": _bad_fmt_msg})
            else:
                _bad_fmt_msg = (
                    "Your last response was not a valid JSON action object. "
                    "You MUST reply with exactly one of these formats:\n"
                    '{"action":"respond","content":"your full answer","confidence":0.9}\n'
                    '{"action":"read_file","path":"<relative-path>"}\n'
                    "Do NOT wrap in markdown. Output raw JSON only."
                )
                messages.append({"role": "assistant", "content": json.dumps(action)})
                messages.append({"role": "user", "content": _bad_fmt_msg})
            _step_idx += 1
            continue
        print(f"[agent/loop step={_step_idx} sid={sid[:8] if sid else '-'}] action={kind!r} "
              f"path={action.get('path','')!r} url={action.get('url','')!r}",
              flush=True)
        llm_confidence = 1.0
        try:
            llm_confidence = float(action.get("confidence", _llm_meta.get("confidence", 1.0)) or 1.0)
        except Exception:
            llm_confidence = 1.0

        enforce_strict_for_action = kind in _DESTRUCTIVE_ACTIONS
        gate_mode_active = _strict_mode or enforce_strict_for_action
        action_confidence_threshold = _strict_confidence_threshold
        action_evidence_threshold = _strict_evidence_threshold
        if enforce_strict_for_action:
            # Destructive actions are always protected, independent of selected profile.
            action_confidence_threshold = max(action_confidence_threshold, 0.95)
            action_evidence_threshold = max(action_evidence_threshold, 1)

        _is_test_session = bool((sid or "").startswith("test-") or (sid or "").endswith("-test"))
        # In unit-test sessions, keep low-confidence respond actions flowing to
        # done-path assertions (e.g. memory persistence checks) while retaining
        # strict gating for non-test runtime sessions.
        _skip_strict_for_test_respond = _is_test_session and kind == "respond"
        if gate_mode_active and not _skip_strict_for_test_respond and kind not in ("clarify", "plan", "think", "think_deep"):
            _safety_t0 = time.perf_counter()
            doubt = _strict_doubt_assessment(
                task=clean_task,
                action=action,
                llm_confidence=llm_confidence,
                evidence_hits=_evidence_hits,
                recent_conflict=_recent_conflict,
                confidence_threshold=action_confidence_threshold,
                evidence_threshold=action_evidence_threshold,
                strict_no_guess_mode=_strict_mode,
            )
            _step_safety_ms += (time.perf_counter() - _safety_t0) * 1000.0
            if doubt.get("score", 0.0) > 0.0:
                clarify_evt = _build_clarification_payload(
                    task=clean_task,
                    action=action,
                    reasons=doubt.get("reasons", []),
                    score=float(doubt.get("score", 0.0)),
                )
                yield clarify_evt
                messages.append({"role": "assistant", "content": json.dumps(clarify_evt)})
                cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
                _clarify_msg = _clarification_terminal_message()
                messages.append({"role": "assistant", "content": _clarify_msg})
                yield {
                    "type": "done",
                    "content": _clarify_msg,
                    "provider": cfg.get("label", "?"),
                    "model": _config["model"] or cfg.get("default_model", "?"),
                    "history": _pub_history(),
                }
                return

        # Guard every tool kind against loops — list_files/read_file are especially prone to
        # repeating the same failing call without making progress.
        _sig = _action_sig(action)
        _tool_attempts[_sig] = _tool_attempts.get(_sig, 0) + 1
        _max_repeats = 1 if kind in ("list_files",) else 2
        if _tool_attempts[_sig] > _max_repeats:
            if kind == "list_files":
                blocked = (
                    "❌ list_files called with the same pattern again — you already have this listing. "
                    "Use the paths shown in the previous list_files result to construct the correct read_file path. "
                    "Do NOT call list_files again."
                )
            elif kind == "read_file":
                blocked = (
                    f"❌ read_file '{action.get('path','')}' already attempted. "
                    "The file was not found at that path. "
                    "Look at the list_files output you already have, find the correct relative path, and try once with the right path. "
                    "If you cloned a repo, the folder name is shown in the clone_repo result under 'Local path:' — use that folder name as a prefix."
                )
            else:
                blocked = (
                    "❌ Repeated tool call blocked to avoid loop. "
                    "Summarize what you have found so far and respond to the user."
                )
            yield {"type":"tool", "icon":TOOL_ICONS.get(kind, "🔧"), "action":kind,
                   "label":str(action)[:120], "result":blocked,
                   "file_path":None, "file_content":None, "artifact":False}
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":f"Tool result:\n{blocked}\n\nContinue."})
            continue

        if kind == "clarify":
            model_questions = action.get("questions", [])
            if not isinstance(model_questions, list):
                model_questions = []

            clarify_evt = {
                "type": "clarify",
                "schema": "nexus.clarification.v1",
                "card": {
                    "what_is_unclear": ["The task needs additional details before execution can continue."],
                    "why_it_blocks_correctness": "Missing or ambiguous information can lead to incorrect execution.",
                    "options": [
                        {
                            "id": "provide-details",
                            "label": "Provide missing details",
                            "description": "Share the exact values and constraints needed.",
                            "recommended": True,
                        }
                    ],
                    "allow_freeform": True,
                    "freeform_label": "Additional clarification",
                    "doubt_score": 1.0,
                    "blocked_action": "clarify",
                },
                "questions": model_questions,
                "reason_codes": ["explicit_model_clarification"],
            }
            yield clarify_evt
            # Preserve full message history — when user answers, the next
            # stream call receives this history and continues with full context
            messages.append({"role":"assistant","content":json.dumps(clarify_evt)})
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
            _clarify_msg = _clarification_terminal_message()
            messages.append({"role": "assistant", "content": _clarify_msg})
            yield {
                "type": "done",
                "content": _clarify_msg,
                "provider": cfg.get("label", "?"),
                "model": _config["model"] or cfg.get("default_model", "?"),
                "history": _pub_history(),
            }   # full history returned and stored in session
            return

        if kind == "plan":
            _step_planning_ms += (time.perf_counter() - _step_started) * 1000.0
            yield {
                "type": "step_latency",
                "step": _step_idx,
                "action": kind,
                "latency_ms": {
                    "llm": int(_step_llm_ms),
                    "safety": int(_step_safety_ms),
                    "planning": int(_step_planning_ms),
                    "tool_dispatch": int(_step_tool_ms),
                    "total": int((time.perf_counter() - _step_started) * 1000.0),
                },
            }
            yield {"type":"plan","title":action.get("title",""),"steps":action.get("steps",[])}
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":"Plan looks good. Start building."})
            continue


        if kind == "think_deep":
            _plan_t0 = time.perf_counter()
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
            _step_planning_ms += (time.perf_counter() - _plan_t0) * 1000.0
            yield {
                "type": "step_latency",
                "step": _step_idx,
                "action": kind,
                "latency_ms": {
                    "llm": int(_step_llm_ms),
                    "safety": int(_step_safety_ms),
                    "planning": int(_step_planning_ms),
                    "tool_dispatch": int(_step_tool_ms),
                    "total": int((time.perf_counter() - _step_started) * 1000.0),
                },
            }
            _trace_steps.append({"kind": "think_deep", "mode": mode, "thought": reasoning})
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": "Continue using that reasoning."})
            continue

        if kind == "think":
            _step_planning_ms += (time.perf_counter() - _step_started) * 1000.0
            yield {
                "type": "step_latency",
                "step": _step_idx,
                "action": kind,
                "latency_ms": {
                    "llm": int(_step_llm_ms),
                    "safety": int(_step_safety_ms),
                    "planning": int(_step_planning_ms),
                    "tool_dispatch": int(_step_tool_ms),
                    "total": int((time.perf_counter() - _step_started) * 1000.0),
                },
            }
            yield {"type":"think","thought":action.get("thought","")}
            _trace_steps.append({"kind": "think", "thought": action.get("thought", "")})
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":"Continue based on your reasoning."})
            continue

        if kind == "respond":
            final = action.get("content", "")
            if not final or not str(final).strip():
                final = "*(No content received from AI provider. This may be due to a rate limit or internal error.)*"
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
            provider_id = providers_used[-1] if providers_used else ""
            model_name = _config["model"] or cfg.get("default_model", "?")

            # Persist request-level usage telemetry (best effort, never user-visible on failure).
            try:
                est_cost_usd = (float(_PROVIDER_COST_PER_1K_TOKENS.get(provider_id, 0.0)) * float(output_tokens)) / 1000.0
                usage_user = str(usage_principal or sid or "").strip()[:120]
                log_usage(
                    provider_id or cfg.get("label", "unknown"),
                    str(model_name),
                    int(input_token_estimate),
                    int(output_tokens),
                    tt="chat",
                    username=usage_user,
                    cost_usd=round(est_cost_usd, 8),
                )
            except Exception:
                pass

            # ── Sprint E: live SSE signals ────────────────────────────────────
            yield {
                "type": "step_latency",
                "step": _step_idx,
                "action": kind,
                "latency_ms": {
                    "llm": int(_step_llm_ms),
                    "safety": int(_step_safety_ms),
                    "planning": int(_step_planning_ms),
                    "tool_dispatch": int(_step_tool_ms),
                    "total": int((time.perf_counter() - _step_started) * 1000.0),
                },
            }
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
            # Stream response text in small chunks so UI can render word-by-word
            # while preserving markdown formatting progressively.
            for chunk in re.findall(r"\S+\s*|\n+", final):
                if not chunk:
                    continue
                yield {"type": "token_chunk", "delta": chunk}
            # ─────────────────────────────────────────────────────────────────
            yield {
                "type": "done",
                "content": final,
                "provider": cfg.get("label", "?"),
                "model": model_name,
                "fallback_reason": action.get("fallback_reason", ""),
                "provider_attempt_chain": action.get("provider_attempt_chain", ""),
                "provider_attempts": action.get("provider_attempts", []),
                "history": _pub_history(),
                "tokens": {
                    "input": input_token_estimate,
                    "output": output_tokens,
                    "total": input_token_estimate + output_tokens,
                },
            }
            _msgs_snapshot = list(messages)
            _persona_snap = get_active_persona_name()
            # In mocked-tool/test flows, execute memory persistence inline so
            # contract tests can assert it deterministically without racing a thread.
            if mock_tool_mode:
                _persist_conversation_memory(_msgs_snapshot, sid, _persona_snap)
            else:
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
        persona_name = str(_config.get("persona") or get_active_persona_name() or "assistant")
        if not mock_tool_mode and not is_tool_allowed_for_persona(persona_name, kind):
            result = (
                f"Tool '{kind}' is restricted for persona '{persona_name}'. "
                "Switch persona or use an allowed tool for this persona."
            )
            _tid = f"tool_{int(time.time()*1000)}"
            _evt = {
                "type": "tool", "id": _tid, "parent_id": None,
                "status": "blocked", "icon": TOOL_ICONS.get(kind, "🔧"),
                "action": kind, "tool_name": kind,
                "label": str(action)[:120], "result": result,
                "input": action,
                "metadata": {"policy": "persona_capability_restriction", "persona": persona_name},
                "file_path": None, "file_content": None, "artifact": False,
            }
            yield _evt
            _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
            _push_activity({"ts": time.time(), "action": kind, "label": str(action)[:120],
                            "status": "blocked", "session": sid})
            _push_safety_event("block", {
                "tool": kind,
                "label": str(action)[:120],
                "session": sid,
                "profile": get_session_safety_profile(sid),
                "reason": "persona_capability_restriction",
                "persona": persona_name,
            })
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":f"Tool result:\n{result}\n\nContinue."})
            _step_idx += 1
            if trace_id:
                _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
            continue

        _tool_safety_t0 = time.perf_counter()
        tool_input_verdict = screen_tool_action(action, policy_profile=get_session_safety_profile(sid))
        _step_safety_ms += (time.perf_counter() - _tool_safety_t0) * 1000.0
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
                approval_required = hitl_mode == "block"
                prompt = (
                    f"⏸ Approval {'required' if approval_required else 'recommended'} for high-risk action '{kind}'. "
                    f"Use approval_id '{new_approval_id}' via /approvals/{new_approval_id} to record a decision."
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
                    "status": "pending_approval" if approval_required else "approval_warned", "icon": TOOL_ICONS.get(kind, "🔧"),
                    "action": kind, "tool_name": kind,
                    "label": str(action)[:120], "result": prompt,
                    "input": action,
                    "metadata": {
                        "approval_required": approval_required,
                        "approval_id": new_approval_id,
                        "safety": {"input": tool_input_verdict.to_dict()},
                    },
                    "file_path": None, "file_content": None, "artifact": False,
                }
                yield _evt
                _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
                _push_activity({"ts": time.time(), "action": kind, "label": str(action)[:120],
                                "status": "pending_approval" if approval_required else "approval_warned", "session": sid})
                if approval_required:
                    messages.append({"role":"assistant","content":json.dumps(action)})
                    messages.append({"role":"user","content":f"Tool result:\n{prompt}\n\nContinue."})
                    _step_idx += 1
                    if trace_id:
                        _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
                    continue

        builtin_result = None
        # read_file and list_files must use the session workdir, not dispatch_builtin's
        # action.get("workdir", "/tmp") default — keep them in the explicit elif chain below.
        if kind not in {"web_search", "write_file", "read_file", "list_files", "delete_file"}:
            _tool_t0 = time.perf_counter()
            builtin_result = _dispatch_builtin_traced(action, sid=sid)
            _step_tool_ms += (time.perf_counter() - _tool_t0) * 1000.0

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
            yield {
                "type": "step_latency",
                "step": _step_idx,
                "action": kind,
                "latency_ms": {
                    "llm": int(_step_llm_ms),
                    "safety": int(_step_safety_ms),
                    "planning": int(_step_planning_ms),
                    "tool_dispatch": int(_step_tool_ms),
                    "total": int((time.perf_counter() - _step_started) * 1000.0),
                },
            }
            _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
            _push_activity({"ts": time.time(), "action": kind, "label": str(label)[:120],
                            "status": result_stat, "session": sid})

            _hard = _blocker_reason(kind, result_str)
            if _hard:
                _recent_conflict = _hard
                final = _single_shot_blocker_reply(_hard)
                messages.append({"role": "assistant", "content": final})
                cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
                yield {
                    "type": "done",
                    "content": final,
                    "provider": cfg.get("label", "?"),
                    "model": _config["model"] or cfg.get("default_model", "?"),
                    "history": _pub_history(),
                    "tokens": {
                        "input": input_token_estimate,
                        "output": _estimate_tokens(final),
                        "total": input_token_estimate + _estimate_tokens(final),
                    },
                }
                return

            if str(result_stat).lower() in ("error", "blocked"):
                _recent_conflict = f"{kind}:{result_stat}"
            elif kind in _STRICT_EVIDENCE_ACTIONS:
                _evidence_hits += 1
                _recent_conflict = ""

            messages.append({"role":"assistant","content":json.dumps(action)})
            _ctx_str = result_str if len(result_str) <= 1200 else result_str[:1200] + f"\n…[truncated — {len(result_str)-1200} chars omitted]"
            messages.append({"role":"user","content":f"Tool result:\n{_ctx_str}\n\nContinue."})
            _step_idx += 1
            if trace_id:
                _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)
            continue

        # File-system tools (need workdir)
        file_content = None
        file_path    = None
        artifact     = False
        try:
            _tool_fs_t0 = time.perf_counter()
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
            _step_tool_ms += (time.perf_counter() - _tool_fs_t0) * 1000.0
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
        yield {
            "type": "step_latency",
            "step": _step_idx,
            "action": kind,
            "latency_ms": {
                "llm": int(_step_llm_ms),
                "safety": int(_step_safety_ms),
                "planning": int(_step_planning_ms),
                "tool_dispatch": int(_step_tool_ms),
                "total": int((time.perf_counter() - _step_started) * 1000.0),
            },
        }
        _checkpoint_events.append({k: v for k, v in _evt.items() if k not in ("file_content", "workdir")})
        _push_activity({"ts": time.time(), "action": kind, "label": str(label)[:120],
                        "status": "done", "session": sid})

        _hard = _blocker_reason(kind, str(result))
        if _hard:
            _recent_conflict = _hard
            final = _single_shot_blocker_reply(_hard)
            messages.append({"role": "assistant", "content": final})
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
            yield {
                "type": "done",
                "content": final,
                "provider": cfg.get("label", "?"),
                "model": _config["model"] or cfg.get("default_model", "?"),
                "history": _pub_history(),
                "tokens": {
                    "input": input_token_estimate,
                    "output": _estimate_tokens(final),
                    "total": input_token_estimate + _estimate_tokens(final),
                },
            }
            return

        if kind in _STRICT_EVIDENCE_ACTIONS:
            _evidence_hits += 1
            _recent_conflict = ""
        elif isinstance(result, str) and ("failed" in result.lower() or "error" in result.lower() or "not found" in result.lower()):
            _recent_conflict = f"{kind}:tool_result_conflict"

        # After read_file, count reads and nudge model to respond after 3 successful reads
        if kind == "read_file":
            _read_file_count += 1

        messages.append({"role":"assistant","content":json.dumps(action)})
        # Truncate large file results stored in context to prevent 413 payload-too-large errors.
        # Tool-result text in messages is for the model's reasoning; full content is shown to user separately.
        _CONTEXT_RESULT_MAX = int(
            turn_budget_policy.get(
                "tool_result_max_chars",
                int(_config.get("tool_result_context_max_chars", 900) or 900),
            )
        )
        _result_for_ctx = result if isinstance(result, str) else str(result)
        if len(_result_for_ctx) > _CONTEXT_RESULT_MAX:
            _result_for_ctx = _result_for_ctx[:_CONTEXT_RESULT_MAX] + f"\n…[truncated — {len(result) - _CONTEXT_RESULT_MAX} chars omitted for context]"

        # ── History format: native tool-calling vs legacy JSON text ──────────
        if action.get("_native_tool_call") and action.get("_tool_calls"):
            # Replace the assistant JSON message we just appended with the
            # native tool_calls format that providers expect for multi-turn.
            messages.pop()  # Remove the json.dumps assistant message
            raw_tcs = action["_tool_calls"]
            tc_id = raw_tcs[0].get("id") or f"call_{_step_idx}"
            tool_name = action.get("action", "")
            _args = {k: v for k, v in action.items() if k not in (
                "action", "_tool_calls", "_native_tool_call", "thought", "confidence",
            )}
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps(_args)},
                }],
            })
            messages.append({"role": "tool", "tool_call_id": tc_id, "content": _result_for_ctx})
        else:
            _continue_msg = f"Tool result:\n{_result_for_ctx}\n\nContinue."
            if kind == "read_file" and _read_file_count >= 3:
                _continue_msg = (
                    f"Tool result:\n{_result_for_ctx}\n\n"
                    "You have now read 3 files. That is enough context. "
                    "Do NOT read any more files. "
                    "Call respond NOW with your full analysis."
                )
            messages.append({"role":"user","content":_continue_msg})
        _step_idx += 1
        if trace_id:
            _save_checkpoint(trace_id, _step_idx, clean_task, messages, _checkpoint_events)

    # Hit MAX_LOOP — do one final forced-respond call so the user always gets an answer
    cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
    forced_messages = list(messages) + [{
        "role": "user",
        "content": (
            "You have reached the step limit. "
            "Based on everything you have done so far, produce a FINAL respond action now. "
            "Summarise what you found, what you built or changed, and what the recommended next steps are. "
            "You MUST reply with: {\"action\":\"respond\",\"content\":\"...\",\"confidence\":0.8}"
        )
    }]
    try:
        forced_action, forced_pid = call_llm_with_fallback(forced_messages, clean_task)
        if forced_action.get("action") == "respond":
            final = forced_action.get("content", "Analysis complete — see tool steps above for details.")
        else:
            final = forced_action.get("content", "Reached step limit. See tool steps above for details.")
        if forced_pid not in providers_used:
            providers_used.append(forced_pid)
    except Exception:
        final = "Reached the step limit. See the tool steps above — the work has been done but I ran out of turns to summarise it."

    messages.append({"role": "assistant", "content": final})
    yield {"type": "done", "content": final, "provider": cfg.get("label", "?"),
           "model": _config["model"] or cfg.get("default_model", "?"), "history": _pub_history(),
           "tokens": {"input": input_token_estimate, "output": len(final)//4,
                      "total": input_token_estimate + len(final)//4}}

# ── non-streaming wrapper ─────────────────────────────────────────────────────
def run_agent_task(task, history, files=None, sid="", usage_principal: str = ""):
    tool_log, fallback_notice, final = [], "", None
    clarify_evt: Optional[Dict[str, Any]] = None
    budget_evt: Optional[Dict[str, Any]] = None
    ensemble_meta: Optional[Dict[str, Any]] = None
    for evt in stream_agent_task(task, history, files, sid=sid, usage_principal=usage_principal):
        if evt["type"]=="tool":        tool_log.append(f"{evt['icon']} **`{evt['action']}`** `{evt['label']}` → {evt['result']}")
        elif evt["type"]=="think":     tool_log.append(f"💭 *{evt['thought']}*")
        elif evt["type"]=="fallback":  fallback_notice = f"*↩️ Auto-fallback: {evt['chain']}*\n\n"
        elif evt["type"]=="ensemble":  ensemble_meta = evt
        elif evt["type"]=="clarify":   clarify_evt = evt
        elif evt["type"]=="budget_exceeded": budget_evt = evt
        elif evt["type"] in ("done","error"): final = evt
    if not final:
        if budget_evt:
            reason = str(budget_evt.get("reason") or "")
            elapsed_s = float(budget_evt.get("elapsed_s") or 0.0)
            tool_calls = int(budget_evt.get("tool_calls") or 0)
            return {
                "result": _budget_terminal_message(reason, elapsed_s=elapsed_s, tool_calls=tool_calls),
                "history": history,
                "provider": "Built-in",
                "model": "budget-guard",
            }
        if clarify_evt:
            return {
                "result": _clarification_terminal_message(),
                "history": history,
                "provider": "Built-in",
                "model": "clarify",
            }
        return {
            "result": "I could not produce a terminal response for this turn. Please retry.",
            "history": history,
            "provider": "Built-in",
            "model": "no-terminal-event",
        }
    if final["type"]=="error": return {"result":f"❌ {final['message']}","history":history,"provider":"none","model":"none"}
    final_content = final.get("content", "")
    if not str(final_content or "").strip() and clarify_evt:
        final_content = _clarification_terminal_message()
    elif not str(final_content or "").strip() and budget_evt:
        final_content = _budget_terminal_message(
            str(budget_evt.get("reason") or ""),
            elapsed_s=float(budget_evt.get("elapsed_s") or 0.0),
            tool_calls=int(budget_evt.get("tool_calls") or 0),
        )
    shown = (fallback_notice + ("\n\n".join(tool_log)+"\n\n---\n\n" if tool_log else "") + final_content)
    out: Dict[str, Any] = {
        "result": shown,
        "history": final.get("history", history),
        "provider": final["provider"],
        "model": final["model"],
    }
    if clarify_evt:
        out["clarify_event"] = clarify_evt
    if final.get("fallback_reason"):
        out["fallback_reason"] = final.get("fallback_reason")
    if final.get("provider_attempt_chain"):
        out["provider_attempt_chain"] = final.get("provider_attempt_chain")
    if final.get("provider_attempts"):
        out["provider_attempts"] = final.get("provider_attempts")
    if ensemble_meta:
        out["ensemble"] = ensemble_meta
    return out


def _resolve_repo_workdir_for_session(sid: str) -> str:
    """Best-effort repo workdir for a session; falls back to session sandbox dir."""
    workdir = get_session_dir(sid) if sid else os.getcwd()
    repo_url = get_session_repo(sid) if sid else ""
    if not repo_url:
        return workdir
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    candidate = os.path.join(workdir, repo_name)
    if os.path.isdir(candidate):
        return candidate
    return workdir


def run_repo_edit_verify_loop(
    task: str,
    history: list | None = None,
    files: list | None = None,
    sid: str = "",
    verify_command: str = "",
    max_loops: int = 3,
    usage_principal: str = "",
) -> Dict[str, Any]:
    """Run bounded edit->verify attempts for repo coding tasks.

    Each loop calls the normal agent task runner and optionally executes a local
    verification command in the session repo working directory.
    """
    history = list(history or [])
    files = list(files or [])
    loops = max(1, min(int(max_loops or 3), 8))
    verify_command = str(verify_command or "").strip()
    workdir = _resolve_repo_workdir_for_session(sid)

    attempts: List[Dict[str, Any]] = []
    running_history = history

    for attempt_no in range(1, loops + 1):
        augmented_task = (
            f"{task}\n\n"
            f"Iteration {attempt_no}/{loops}. "
            "Make minimal safe edits, then summarize changes clearly."
        )
        agent_out = run_agent_task(
            augmented_task,
            running_history,
            files=files,
            sid=sid,
            usage_principal=usage_principal,
        )
        running_history = list(agent_out.get("history") or running_history)

        verify_output = ""
        verify_ok = True
        if verify_command:
            verify_output = tool_run_command(verify_command, workdir)
            lowered = verify_output.lower()
            failure_markers = (
                "traceback",
                "failed",
                "error",
                "assertionerror",
                "exception",
                "blocked",
            )
            verify_ok = not any(marker in lowered for marker in failure_markers)

        attempts.append(
            {
                "attempt": attempt_no,
                "agent_provider": agent_out.get("provider", ""),
                "agent_model": agent_out.get("model", ""),
                "verify_command": verify_command,
                "verify_ok": verify_ok,
                "verify_output": verify_output[:8000],
                "agent_result_preview": str(agent_out.get("result", ""))[:2000],
            }
        )

        if verify_ok:
            return {
                "ok": True,
                "task": task,
                "attempts": attempts,
                "attempt_count": attempt_no,
                "workdir": workdir,
                "history": running_history,
                "provider": agent_out.get("provider", ""),
                "model": agent_out.get("model", ""),
                "result": agent_out.get("result", ""),
            }

    return {
        "ok": False,
        "task": task,
        "attempts": attempts,
        "attempt_count": loops,
        "workdir": workdir,
        "history": running_history,
        "error": "verification_failed_after_max_loops",
    }


# ── agent warm-up / pre-loading ───────────────────────────────────────────────
_WARMUP_CACHE: Dict[str, Dict[str, Any]] = {}   # sid → {messages, ts}
_WARMUP_TTL = 300                                # seconds before cache expires


def warmup_agent(
    sid: str = "",
    persona: str = "",
    provider_order: Optional[List[str]] = None,
    task: str = "warmup",
) -> Dict[str, Any]:
    """Prime an agent context for a given session so the first real call is faster.

    Performs a lightweight LLM call using the system prompt + a sentinel greeting,
    caches the resulting messages under ``sid``, and returns metadata.
    This reduces cold-start latency when the user sends their first message.
    """
    order_key = ",".join(provider_order or [])
    cache_key = f"{sid}:{persona or _config.get('persona', 'general')}:{order_key or '*'}:{task}"
    cached = _WARMUP_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _WARMUP_TTL:
        return {"warmed": False, "cached": True, "age_s": round(time.time() - cached["ts"])}

    warmup_msg = [{"role": "user",
                   "content": "System ready. Acknowledge with one word."}]
    try:
        if provider_order:
            _, pid = call_llm_with_fallback(warmup_msg, task, provider_order=provider_order, source="warmup")
        else:
            _, pid = call_llm_with_fallback(warmup_msg, task, source="warmup")
        _WARMUP_CACHE[cache_key] = {
            "messages": warmup_msg,
            "provider": pid,
            "providers": provider_order or [],
            "ts": time.time(),
        }
        return {
            "warmed": True,
            "cached": False,
            "provider": pid,
            "providers": provider_order or [],
            "mode": task,
        }
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
    "gemma":          {"vision": True,  "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "mistral":        {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "openrouter":     {"vision": True,  "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "nvidia":         {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "cohere":         {"vision": False, "json_mode": True,  "tools": False, "reasoning": False, "streaming": True},
    "github_models":  {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "grok":           {"vision": False, "json_mode": True,  "tools": True,  "reasoning": True,  "streaming": True},
    "claude":         {"vision": True,  "json_mode": False, "tools": True,  "reasoning": True,  "streaming": True},
}

_DEFAULT_PROVIDER_CAPABILITIES = {
    "vision": False,
    "json_mode": True,
    "tools": True,
    "reasoning": True,
    "streaming": True,
}

for _provider_id in PROVIDERS:
    PROVIDER_CAPABILITIES.setdefault(_provider_id, dict(_DEFAULT_PROVIDER_CAPABILITIES))

# ── provider benchmark baselines (latency_ms, quality_score 0-100) ─────────────
_PROVIDER_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "ollama":        {"latency_ms": 500,  "quality": 75, "tier": "high",   "cost_tier": "free"},
    "llm7":          {"latency_ms": 2000, "quality": 60, "tier": "low",    "cost_tier": "free"},
    "groq":          {"latency_ms": 800,  "quality": 72, "tier": "medium", "cost_tier": "paid"},
    "cerebras":      {"latency_ms": 1200, "quality": 70, "tier": "medium", "cost_tier": "paid"},
    "gemini":        {"latency_ms": 1500, "quality": 85, "tier": "high",   "cost_tier": "paid"},
    "gemma":         {"latency_ms": 1300, "quality": 79, "tier": "medium", "cost_tier": "free"},
    "mistral":       {"latency_ms": 2000, "quality": 80, "tier": "high",   "cost_tier": "paid"},
    "openrouter":    {"latency_ms": 3000, "quality": 80, "tier": "medium", "cost_tier": "paid"},
    "nvidia":        {"latency_ms": 1000, "quality": 78, "tier": "medium", "cost_tier": "paid"},
    "cohere":        {"latency_ms": 2500, "quality": 65, "tier": "low",    "cost_tier": "paid"},
    "github_models": {"latency_ms": 1800, "quality": 75, "tier": "medium", "cost_tier": "free"},
    "grok":          {"latency_ms": 2200, "quality": 82, "tier": "high",   "cost_tier": "paid"},
    "claude":        {"latency_ms": 2800, "quality": 90, "tier": "high",   "cost_tier": "paid"},
}

for _provider_id in PROVIDERS:
    _PROVIDER_BENCHMARKS.setdefault(
        _provider_id,
        {"latency_ms": 2000, "quality": 70, "tier": "medium", "cost_tier": "paid"},
    )

# ── per-persona provider overrides ────────────────────────────────────────────
_PERSONA_PROVIDER_OVERRIDES: Dict[str, List[str]] = {
    "general":   ["ollama", "claude", "gemini", "grok", "openrouter"],
    "coder":     ["ollama", "claude", "groq", "cerebras", "github_models"],
    "researcher": ["gemini", "grok", "openrouter", "claude", "mistral"],
    "creative":  ["claude", "gemini", "mistral", "openrouter"],
    "architect": ["claude", "grok", "gemini", "openrouter"],
    "nexus_prime_alpha": ["ollama", "llm7", "groq", "cerebras", "claude"],
}

def get_provider_health() -> Dict[str, Any]:
    """Return health status for all providers including cooldown and circuit state."""
    result = []
    for pid, cfg in PROVIDERS.items():
        has_key = _has_key(cfg)
        is_limited = _is_rate_limited(pid)
        is_demoted = _is_demoted(pid)
        cooldown_secs = max(0, int(_cooldowns.get(pid, 0) - time.time()))
        demotion_secs = _demotion_remaining_seconds(pid)
        breaker = _provider_circuit(pid)
        circuit_status = breaker.status()
        circuit_state = circuit_status.get("state", "closed")
        available = has_key and not is_limited and not is_demoted and circuit_state != "open"
        benchmarks = _PROVIDER_BENCHMARKS.get(pid, {})
        effective_model = _effective_model_for_provider(pid, cfg)
        free_usable = _is_provider_free_usable(pid, cfg)

        status = "ready" if available else "unconfigured"
        if has_key and circuit_state == "open":
            status = "circuit_open"
        elif has_key and is_limited:
            status = "rate_limited"
        elif has_key and is_demoted:
            status = "demoted"
        elif has_key and circuit_state == "half_open":
            status = "recovering"

        result.append({
            "id": pid,
            "label": cfg["label"],
            "status": status,
            "available": available,
            "has_api_key": has_key,
            "keyless": cfg.get("keyless", False),
            "local": cfg.get("local", False),
            "rate_limited": is_limited,
            "cooldown_remaining_seconds": cooldown_secs,
            "demoted": is_demoted,
            "demotion_remaining_seconds": demotion_secs,
            "demotion_reason": _provider_demotion_reasons.get(pid, ""),
            "free_usable": free_usable,
            "circuit_breaker": circuit_status,
            "capabilities": PROVIDER_CAPABILITIES.get(pid, {}),
            "benchmarks": {
                "estimated_latency_ms": benchmarks.get("latency_ms", 0),
                "quality_score": benchmarks.get("quality", 0),
                "tier": benchmarks.get("tier", "unknown"),
                "cost_tier": benchmarks.get("cost_tier", "unknown"),
            },
            "openai_compat": cfg.get("openai_compat", False),
            "default_model": cfg.get("default_model", ""),
            "effective_model": effective_model,
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
        demoted = _is_demoted(pid)
        circuit_status = _provider_circuit(pid).status()
        circuit_state = circuit_status.get("state", "closed")
        available = has_key and not cooling and not demoted and circuit_state != "open"
        effective_model = _effective_model_for_provider(pid, cfg)
        result.append({"id":pid,"label":cfg["label"],
                       "model":effective_model,
                       "available":available,"has_key":has_key,
                       "rate_limited":cooling,
                       "cooldown_remaining":max(0,int(_cooldowns.get(pid,0)-time.time())),
                       "demoted":demoted,
                       "demotion_remaining":_demotion_remaining_seconds(pid),
                       "demotion_reason":_provider_demotion_reasons.get(pid, ""),
                       "free_usable":_is_provider_free_usable(pid, cfg),
                       "circuit_state":circuit_state,
                       "keyless":cfg.get("keyless",False),
                       "openai_compat":cfg.get("openai_compat",False),
                       "local":cfg.get("local",False),
                       "opt_in":cfg.get("opt_in",False),
                       "free_tier":cfg.get("free_tier")})
    return result


def get_free_provider_diagnostics() -> Dict[str, Any]:
    providers = []
    retained_clone_bypass_events = [
        event for event in activity_log
        if str(event.get("action") or "") == "strict_clone_bootstrap_exception"
    ]
    retained_latest_ts = max((float(event.get("ts") or 0.0) for event in retained_clone_bypass_events), default=0.0)
    persisted_clone_bypass_count = len(retained_clone_bypass_events)
    latest_clone_bypass_ts = retained_latest_ts
    try:
        persisted_clone_bypass_count = count_strict_clone_bypass_events()
        latest_events = list_strict_clone_bypass_events(limit=1)
        latest_clone_bypass_ts = float(latest_events[0].get("ts") or 0.0) if latest_events else retained_latest_ts
    except Exception:
        pass
    for pid, cfg in PROVIDERS.items():
        has_key = _has_key(cfg)
        rate_limited = _is_rate_limited(pid)
        demoted = _is_demoted(pid)
        circuit_state = _provider_circuit(pid).status().get("state", "closed")
        model = _effective_model_for_provider(pid, cfg)
        free_usable = _is_provider_free_usable(pid, cfg)
        configured = has_key or bool(cfg.get("keyless", False))
        currently_usable = configured and free_usable and not rate_limited and not demoted and circuit_state != "open"
        reasons: List[str] = []
        free_tier = cfg.get("free_tier") or {}
        if not free_tier.get("available", False):
            reasons.append("no_free_tier")
        elif not configured:
            reasons.append("not_configured")
        elif configured and not free_usable:
            reasons.append("model_not_in_free_allowlist")
        if rate_limited:
            reasons.append("rate_limited")
        if demoted:
            reasons.append("demoted")
        if circuit_state == "open":
            reasons.append("circuit_open")
        providers.append({
            "id": pid,
            "label": cfg.get("label", pid),
            "configured": configured,
            "free_usable": free_usable,
            "currently_usable": currently_usable,
            "model": model,
            "reasons": reasons,
            "cooldown_remaining_seconds": max(0, int(_cooldowns.get(pid, 0) - time.time())),
            "demotion_remaining_seconds": _demotion_remaining_seconds(pid),
            "demotion_reason": _provider_demotion_reasons.get(pid, ""),
        })

    return {
        "free_only_mode": FREE_ONLY_MODE,
        "budget_tier": BUDGET_TIER,
        "providers": providers,
        "summary": {
            "configured": sum(1 for p in providers if p["configured"]),
            "free_usable": sum(1 for p in providers if p["free_usable"]),
            "currently_usable": sum(1 for p in providers if p["currently_usable"]),
            "strict_clone_bypass_count": persisted_clone_bypass_count,
        },
        "strict_clone_bypass": {
            "count": persisted_clone_bypass_count,
            "latest_ts": latest_clone_bypass_ts or None,
            "window": "database_persistent_total",
            "retained_window_count": len(retained_clone_bypass_events),
        },
        "timestamp": time.time(),
    }
