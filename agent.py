import os
import json
import glob
import time
import requests
import subprocess
from typing import Dict, Any, List, Optional

# ── env ───────────────────────────────────────────────────────────────────────
PROVIDER  = os.getenv("PROVIDER", "auto").lower()   # "auto" = try all in order
REPO_DIR  = os.getenv("REPO_DIR", "/tmp/repo")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GH_TOKEN    = os.getenv("GH_TOKEN")
MAX_LOOP    = 6

# ── provider registry ─────────────────────────────────────────────────────────
# Order matters — auto-fallback tries them top to bottom.
# Tweak the order to match your preferred/most generous free tiers first.
PROVIDERS: Dict[str, Dict] = {
    "llm7": {
        "label":         "LLM7.io",
        "base_url":      "https://api.llm7.io/v1",
        "env_key":       "LLM7_API_KEY",
        "default_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "openai_compat": True,
        "keyless":       True,   # works without an API key
    },
    "groq": {
        "label":         "Groq",
        "base_url":      "https://api.groq.com/openai/v1",
        "env_key":       "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "openai_compat": True,
    },
    "cerebras": {
        "label":         "Cerebras",
        "base_url":      "https://api.cerebras.ai/v1",
        "env_key":       "CEREBRAS_API_KEY",
        "default_model": "llama-3.3-70b",
        "openai_compat": True,
    },
    "gemini": {
        "label":         "Google Gemini",
        "base_url":      "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key":       "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
        "openai_compat": True,
    },
    "mistral": {
        "label":         "Mistral AI",
        "base_url":      "https://api.mistral.ai/v1",
        "env_key":       "MISTRAL_API_KEY",
        "default_model": "mistral-small-latest",
        "openai_compat": True,
    },
    "openrouter": {
        "label":         "OpenRouter",
        "base_url":      "https://openrouter.ai/api/v1",
        "env_key":       "OPENROUTER_API_KEY",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "openai_compat": True,
    },
    "nvidia": {
        "label":         "NVIDIA NIM",
        "base_url":      "https://integrate.api.nvidia.com/v1",
        "env_key":       "NVIDIA_API_KEY",
        "default_model": "meta/llama-3.3-70b-instruct",
        "openai_compat": True,
    },
    "cohere": {
        "label":         "Cohere",
        "base_url":      "https://api.cohere.com/compatibility/v1",
        "env_key":       "COHERE_API_KEY",
        "default_model": "command-r-plus",
        "openai_compat": True,
    },
    "github_models": {
        "label":         "GitHub Models",
        "base_url":      "https://models.inference.ai.azure.com",
        "env_key":       "GITHUB_MODELS_TOKEN",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "openai_compat": True,
    },
    "grok": {
        "label":         "Grok (xAI)",
        "env_key":       "GROK_API_KEY",
        "default_model": "grok-3",
        "openai_compat": False,
    },
    "claude": {
        "label":         "Claude (Anthropic)",
        "env_key":       "CLAUDE_API_KEY",
        "default_model": "claude-sonnet-4-20250514",
        "openai_compat": False,
    },
}

# ── rate-limit cooldown tracking ──────────────────────────────────────────────
# { provider_id: unix_timestamp_when_cooldown_expires }
_cooldowns: Dict[str, float] = {}
COOLDOWN_SECONDS = int(os.getenv("RATE_LIMIT_COOLDOWN", "60"))


def _is_rate_limited(provider_id: str) -> bool:
    expires = _cooldowns.get(provider_id, 0)
    return time.time() < expires


def _mark_rate_limited(provider_id: str) -> None:
    _cooldowns[provider_id] = time.time() + COOLDOWN_SECONDS
    print(f"⏳ {provider_id} rate-limited, cooling down for {COOLDOWN_SECONDS}s")


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect 429s and common rate-limit message patterns."""
    msg = str(exc).lower()
    if isinstance(exc, requests.HTTPError):
        if exc.response is not None and exc.response.status_code == 429:
            return True
        # some providers return 429 body in a 200 :(
        try:
            body = exc.response.json()
            code = body.get("error", {}).get("code", "")
            if "rate" in str(code).lower() or "limit" in str(code).lower():
                return True
        except Exception:
            pass
    rate_phrases = ["rate limit", "rate_limit", "too many requests", "quota exceeded",
                    "ratelimit", "throttl", "capacity"]
    return any(p in msg for p in rate_phrases)


# ── provider availability ─────────────────────────────────────────────────────
def _has_key(cfg: Dict) -> bool:
    if cfg.get("keyless"):
        return True
    return bool(os.getenv(cfg["env_key"], "").strip())


def _available_providers() -> List[str]:
    """All providers that have a key set AND are not in cooldown."""
    return [
        pid for pid, cfg in PROVIDERS.items()
        if _has_key(cfg) and not _is_rate_limited(pid)
    ]


def _fallback_order() -> List[str]:
    """
    If PROVIDER is 'auto', return all available providers in registry order.
    Otherwise, put the chosen provider first, then fall back to others.
    """
    available = _available_providers()
    if PROVIDER == "auto":
        return available
    # explicit provider first, then the rest
    ordered = [PROVIDER] if PROVIDER in available else []
    ordered += [p for p in available if p != PROVIDER]
    return ordered


# ── tool description ───────────────────────────────────────────────────────────
TOOLS_DESCRIPTION = """You are a self-hosted code agent. You can respond conversationally OR call tools.
Reply ONLY with valid JSON — no markdown fences, no extra text.

Available actions (pick one per reply):

  { "action": "respond",      "content": "<markdown text>" }
  { "action": "write_file",   "path": "relative/path.ext", "content": "..." }
  { "action": "read_file",    "path": "relative/path.ext" }
  { "action": "list_files",   "pattern": "**/*.py" }
  { "action": "delete_file",  "path": "relative/path.ext" }
  { "action": "run_command",  "cmd": "ls -la" }
  { "action": "commit_push",  "message": "feat: ..." }

Rules:
- Always finish a code-edit task with commit_push.
- list_files pattern is a glob (e.g. "**/*" or "*.md").
- run_command is restricted to safe, non-destructive operations.
- read_file returns the file contents so you can reason about it first.
"""

# ── repo helpers ──────────────────────────────────────────────────────────────
def setup_repo() -> None:
    if os.path.exists(os.path.join(REPO_DIR, ".git")):
        return
    if not GITHUB_REPO or not GH_TOKEN:
        raise Exception(f"Missing env vars. GITHUB_REPO={bool(GITHUB_REPO)}, GH_TOKEN={bool(GH_TOKEN)}")
    auth_url = GITHUB_REPO.replace("https://github.com", f"https://{GH_TOKEN}@github.com")
    result = subprocess.run(
        ["git", "clone", auth_url, REPO_DIR],
        capture_output=True, text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise Exception(f"Git clone failed: {result.stderr}")


def _git(args: List[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-C", REPO_DIR] + args, capture_output=True, text=True, env=env)


# ── tool executors ────────────────────────────────────────────────────────────
def tool_write_file(path: str, content: str) -> str:
    full = os.path.join(REPO_DIR, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {path} ({len(content)} chars)"


def tool_read_file(path: str) -> str:
    full = os.path.join(REPO_DIR, path)
    if not os.path.exists(full):
        return f"File not found: {path}"
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    lines = content.splitlines()
    preview = "\n".join(lines[:300])
    suffix = f"\n... ({len(lines) - 300} more lines)" if len(lines) > 300 else ""
    return f"```\n{preview}{suffix}\n```"


def tool_list_files(pattern: str = "**/*") -> str:
    matches = glob.glob(os.path.join(REPO_DIR, pattern), recursive=True)
    rel = [os.path.relpath(m, REPO_DIR) for m in sorted(matches) if os.path.isfile(m)]
    return "\n".join(rel) if rel else "(no files found)"


def tool_delete_file(path: str) -> str:
    full = os.path.join(REPO_DIR, path)
    if not os.path.exists(full):
        return f"Not found: {path}"
    os.remove(full)
    return f"Deleted {path}"


def tool_run_command(cmd: str) -> str:
    BLOCKED = ["rm -rf", "sudo", "curl", "wget", "nc ", "ncat", "bash -c", "sh -c"]
    for b in BLOCKED:
        if b in cmd:
            return f"Blocked command: {cmd}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=REPO_DIR, timeout=15)
    out = (result.stdout + result.stderr).strip()
    return out[:3000] if out else "(no output)"


def tool_commit_push(message: str = "Claude Alt update") -> str:
    _git(["config", "user.name", "Claude-Alt-Agent"])
    _git(["config", "user.email", "agent@nohands.company"])
    _git(["add", "."])
    commit = _git(["commit", "-m", message])
    if commit.returncode != 0 and "nothing to commit" in commit.stdout:
        return "Nothing to commit."
    if not GITHUB_REPO:
        return "No GITHUB_REPO set, skipped push."
    push_url = GITHUB_REPO.replace("https://github.com", f"https://{GH_TOKEN}@github.com")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", "-C", REPO_DIR, "push", push_url], capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        raise Exception(f"Push failed: {result.stderr}")
    return f"Committed & pushed: {message}"


def dispatch_tool(action: Dict[str, Any]) -> str:
    kind = action.get("action")
    if kind == "write_file":   return tool_write_file(action["path"], action["content"])
    if kind == "read_file":    return tool_read_file(action["path"])
    if kind == "list_files":   return tool_list_files(action.get("pattern", "**/*"))
    if kind == "delete_file":  return tool_delete_file(action["path"])
    if kind == "run_command":  return tool_run_command(action["cmd"])
    if kind == "commit_push":  return tool_commit_push(action.get("message", "Claude Alt update"))
    return f"Unknown action: {kind}"


# ── LLM callers (one per wire format) ────────────────────────────────────────
def _parse_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def _call_openai_compat(cfg: Dict, messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv(cfg["env_key"], "") or ("llm7" if cfg.get("keyless") else "")
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model":       os.getenv("LLM_MODEL", cfg["default_model"]),
        "messages":    [{"role": "system", "content": TOOLS_DESCRIPTION}] + messages,
        "temperature": 0.2,
        "max_tokens":  4096,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    return _parse_json(raw)


def _call_grok(messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv("GROK_API_KEY", "")
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model":       os.getenv("LLM_MODEL", "grok-3"),
        "messages":    [{"role": "system", "content": TOOLS_DESCRIPTION}] + messages,
        "temperature": 0.2,
        "max_tokens":  4096,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    return _parse_json(raw)


def _call_claude(messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv("CLAUDE_API_KEY", "")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }
    payload = {
        "model":      os.getenv("LLM_MODEL", "claude-sonnet-4-20250514"),
        "system":     TOOLS_DESCRIPTION,
        "messages":   messages,
        "max_tokens": 4096,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"]
    return _parse_json(raw)


def _call_single_provider(provider_id: str, messages: List[Dict]) -> Dict[str, Any]:
    """Call one specific provider. Raises on any error."""
    cfg = PROVIDERS[provider_id]
    if cfg["openai_compat"]:
        return _call_openai_compat(cfg, messages)
    if provider_id == "grok":
        return _call_grok(messages)
    if provider_id == "claude":
        return _call_claude(messages)
    raise ValueError(f"No caller implemented for: {provider_id}")


# ── auto-fallback caller ──────────────────────────────────────────────────────
class AllProvidersExhausted(Exception):
    pass


def call_llm_with_fallback(messages: List[Dict]) -> tuple[Dict[str, Any], str]:
    """
    Try providers in order. On rate-limit, mark cooldown and try the next.
    Returns (action_dict, provider_id_that_succeeded).
    Raises AllProvidersExhausted if every provider is rate-limited or errored.
    """
    order = _fallback_order()
    if not order:
        raise AllProvidersExhausted("No providers are available (all rate-limited or no keys set).")

    last_error: Optional[Exception] = None

    for pid in order:
        if _is_rate_limited(pid):
            continue
        try:
            result = _call_single_provider(pid, messages)
            return result, pid
        except Exception as e:
            last_error = e
            if _is_rate_limit_error(e):
                _mark_rate_limited(pid)
                print(f"↩️  {pid} rate-limited, trying next provider…")
            else:
                # Non-rate-limit error: log and skip this provider
                print(f"⚠️  {pid} error ({type(e).__name__}: {e}), skipping…")

    raise AllProvidersExhausted(
        f"All providers exhausted. Last error: {last_error}"
    )


# ── agent loop ────────────────────────────────────────────────────────────────
def run_agent_task(task: str, history: list | None = None) -> Dict[str, Any]:
    try:
        setup_repo()
    except Exception as e:
        print(f"setup_repo warning: {e}")

    messages: List[Dict] = list(history or [])
    messages.append({"role": "user", "content": task})

    tool_log:     List[str] = []
    final_response = ""
    providers_used: List[str] = []   # track which providers got used this turn

    for _ in range(MAX_LOOP):
        try:
            action, used_pid = call_llm_with_fallback(messages)
        except AllProvidersExhausted as e:
            return {
                "result":         f"❌ {e}",
                "history":        messages,
                "provider":       "none",
                "model":          "none",
                "providers_used": providers_used,
            }

        cfg = PROVIDERS[used_pid]
        if used_pid not in providers_used:
            providers_used.append(used_pid)

        if action.get("action") == "respond":
            final_response = action.get("content", "")
            messages.append({"role": "assistant", "content": final_response})
            break

        tool_result = dispatch_tool(action)
        icon = {"write_file": "📝", "read_file": "📖", "list_files": "📂",
                "delete_file": "🗑️", "run_command": "⚙️", "commit_push": "🚀"}.get(action["action"], "🔧")
        tool_log.append(f"{icon} **`{action['action']}`** → {tool_result}")

        messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
        messages.append({"role": "user", "content": f"Tool result:\n{tool_result}\n\nContinue."})
    else:
        final_response = "Agent reached max tool-call limit."
        messages.append({"role": "assistant", "content": final_response})

    shown = ("\n\n".join(tool_log) + "\n\n---\n\n" + final_response) if tool_log else final_response

    # Show fallback notice if we had to hop providers
    if len(providers_used) > 1:
        hops = " → ".join(PROVIDERS[p]["label"] for p in providers_used)
        shown = f"*↩️ Auto-fallback: {hops}*\n\n" + shown

    active_pid  = providers_used[-1] if providers_used else "none"
    active_cfg  = PROVIDERS.get(active_pid, {})

    return {
        "result":         shown,
        "history":        messages,
        "provider":       active_cfg.get("label", active_pid),
        "model":          os.getenv("LLM_MODEL", active_cfg.get("default_model", "?")),
        "providers_used": providers_used,
    }


# ── UI helpers ────────────────────────────────────────────────────────────────
def get_providers_list() -> List[Dict]:
    result = []
    for pid, cfg in PROVIDERS.items():
        has_key    = _has_key(cfg)
        cooling    = _is_rate_limited(pid)
        expires_in = max(0, int(_cooldowns.get(pid, 0) - time.time()))
        result.append({
            "id":          pid,
            "label":       cfg["label"],
            "model":       os.getenv("LLM_MODEL", cfg["default_model"]),
            "available":   has_key and not cooling,
            "has_key":     has_key,
            "rate_limited": cooling,
            "cooldown_remaining": expires_in,
            "active":      pid == PROVIDER or PROVIDER == "auto",
            "keyless":     cfg.get("keyless", False),
        })
    return result
