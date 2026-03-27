import os
import re
import json
import glob
import time
import base64
import requests
import subprocess
import threading
from datetime import datetime
from typing import Dict, Any, List, Iterator, Optional

# ── runtime config (can be patched by /settings endpoint) ────────────────────
_config: Dict[str, Any] = {
    "provider":    os.getenv("PROVIDER", "auto").lower(),
    "model":       os.getenv("LLM_MODEL", ""),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.2")),
}

def get_config() -> Dict[str, Any]:
    return dict(_config)

def update_config(provider: str | None = None, model: str | None = None,
                  temperature: float | None = None) -> Dict[str, Any]:
    if provider    is not None: _config["provider"]    = provider.lower()
    if model       is not None: _config["model"]       = model
    if temperature is not None: _config["temperature"] = float(temperature)
    return dict(_config)

# ── env ───────────────────────────────────────────────────────────────────────
REPO_DIR    = os.getenv("REPO_DIR", "/tmp/repo")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GH_TOKEN    = os.getenv("GH_TOKEN")
MAX_LOOP    = 8
COOLDOWN_SECONDS = int(os.getenv("RATE_LIMIT_COOLDOWN", "60"))

# ── provider registry ─────────────────────────────────────────────────────────
PROVIDERS: Dict[str, Dict] = {
    "llm7": {
        "label": "LLM7.io", "base_url": "https://api.llm7.io/v1",
        "env_key": "LLM7_API_KEY", "default_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "openai_compat": True, "keyless": True,
    },
    "groq": {
        "label": "Groq", "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY", "default_model": "llama-3.3-70b-versatile",
        "openai_compat": True,
    },
    "cerebras": {
        "label": "Cerebras", "base_url": "https://api.cerebras.ai/v1",
        "env_key": "CEREBRAS_API_KEY", "default_model": "llama-3.3-70b",
        "openai_compat": True,
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GEMINI_API_KEY", "default_model": "gemini-2.0-flash",
        "openai_compat": True,
    },
    "mistral": {
        "label": "Mistral AI", "base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY", "default_model": "mistral-small-latest",
        "openai_compat": True,
    },
    "openrouter": {
        "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "openai_compat": True,
    },
    "nvidia": {
        "label": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1",
        "env_key": "NVIDIA_API_KEY", "default_model": "meta/llama-3.3-70b-instruct",
        "openai_compat": True,
    },
    "cohere": {
        "label": "Cohere", "base_url": "https://api.cohere.com/compatibility/v1",
        "env_key": "COHERE_API_KEY", "default_model": "command-r-plus",
        "openai_compat": True,
    },
    "github_models": {
        "label": "GitHub Models", "base_url": "https://models.inference.ai.azure.com",
        "env_key": "GITHUB_MODELS_TOKEN",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "openai_compat": True,
    },
    "grok": {
        "label": "Grok (xAI)", "env_key": "GROK_API_KEY",
        "default_model": "grok-3", "openai_compat": False,
    },
    "claude": {
        "label": "Claude (Anthropic)", "env_key": "CLAUDE_API_KEY",
        "default_model": "claude-sonnet-4-20250514", "openai_compat": False,
    },
}

# ── cooldown tracking ─────────────────────────────────────────────────────────
_cooldowns: Dict[str, float] = {}

def _is_rate_limited(pid: str) -> bool:
    return time.time() < _cooldowns.get(pid, 0)

def _mark_rate_limited(pid: str) -> None:
    cfg = PROVIDERS.get(pid, {})
    cooldown = 15 if cfg.get("keyless") else COOLDOWN_SECONDS
    _cooldowns[pid] = time.time() + cooldown
    print(f"⏳ {pid} rate-limited, cooling {cooldown}s")

def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        if exc.response.status_code == 429:
            return True
        try:
            code = str(exc.response.json().get("error", {}).get("code", "")).lower()
            if "rate" in code or "limit" in code:
                return True
        except Exception:
            pass
    return any(p in msg for p in ["rate limit", "rate_limit", "too many requests",
                                   "quota exceeded", "ratelimit", "throttl"])

def _has_key(cfg: Dict) -> bool:
    return cfg.get("keyless", False) or bool(os.getenv(cfg["env_key"], "").strip())

def _fallback_order() -> List[str]:
    provider = _config["provider"]
    available = [pid for pid, cfg in PROVIDERS.items()
                 if _has_key(cfg) and not _is_rate_limited(pid)]
    if provider == "auto":
        return available
    ordered = [provider] if provider in available else []
    ordered += [p for p in available if p != provider]
    return ordered

# ── direct intent detection ───────────────────────────────────────────────────
_TIME_RE = re.compile(
    r'\b(what(?:\'s| is)(?: the)? (?:current )?time(?: in| at)?|'
    r'current time(?: in)?|time(?: right)? now(?: in)?|'
    r'what time(?: is it)?(?: in)?)\b', re.IGNORECASE)
_DATE_RE = re.compile(
    r'\b(what(?:\'s| is)(?: the)? (?:current |today\'?s? )?date|'
    r'today\'?s? date|what day is(?: it| today))\b', re.IGNORECASE)

def _extract_location(text: str) -> str:
    m = re.search(r'\b(?:in|at|for)\s+([A-Za-z][A-Za-z\s/]{1,30})\??$', text, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip('?').strip()
    return "UTC"

def _try_direct_answer(task: str) -> str | None:
    if _TIME_RE.search(task):
        return tool_get_time(_extract_location(task))
    if _DATE_RE.search(task):
        return tool_get_time("UTC")
    return None

# ── tool description ──────────────────────────────────────────────────────────
TOOLS_DESCRIPTION = """You are a self-hosted code agent with web access. Reply ONLY with valid JSON.

Available actions (pick one per reply):

  { "action": "think",        "thought": "reasoning before acting..." }
  { "action": "respond",      "content": "<markdown>" }
  { "action": "get_time",     "timezone": "Europe/Stockholm" }
  { "action": "web_search",   "query": "search terms" }
  { "action": "write_file",   "path": "relative/path.ext", "content": "..." }
  { "action": "read_file",    "path": "relative/path.ext" }
  { "action": "list_files",   "pattern": "**/*.py" }
  { "action": "delete_file",  "path": "relative/path.ext" }
  { "action": "run_command",  "cmd": "git log --oneline -5" }
  { "action": "commit_push",  "message": "feat: ..." }

Rules:
- Use "think" before complex multi-step tasks to plan your approach.
- Use get_time for ANY time/date/timezone question — never web_search for this.
- Use web_search when asked about current events, docs, or anything you're unsure of.
- Always finish code-edit tasks with commit_push.
- run_command: no destructive operations.
"""

# ── repo helpers ──────────────────────────────────────────────────────────────
def setup_repo() -> None:
    if os.path.exists(os.path.join(REPO_DIR, ".git")):
        return
    if not GITHUB_REPO or not GH_TOKEN:
        raise Exception("Missing GITHUB_REPO or GH_TOKEN")
    auth_url = GITHUB_REPO.replace("https://github.com", f"https://{GH_TOKEN}@github.com")
    r = subprocess.run(["git", "clone", auth_url, REPO_DIR],
                       capture_output=True, text=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode != 0:
        raise Exception(f"Git clone failed: {r.stderr}")

def _git(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", REPO_DIR] + args,
                          capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})

# ── tools ─────────────────────────────────────────────────────────────────────
def tool_get_time(timezone: str = "UTC") -> str:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        ALIASES = {
            "sweden": "Europe/Stockholm", "stockholm": "Europe/Stockholm",
            "uk": "Europe/London", "london": "Europe/London",
            "new york": "America/New_York", "nyc": "America/New_York",
            "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
            "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo",
            "paris": "Europe/Paris", "france": "Europe/Paris",
            "berlin": "Europe/Berlin", "germany": "Europe/Berlin",
            "dubai": "Asia/Dubai", "uae": "Asia/Dubai",
            "sydney": "Australia/Sydney", "australia": "Australia/Sydney",
            "jakarta": "Asia/Jakarta", "indonesia": "Asia/Jakarta",
            "utc": "UTC", "gmt": "GMT",
        }
        key = timezone.lower().strip()
        tz_name = ALIASES.get(key, timezone)
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            return f"Unknown timezone: '{timezone}'. Try e.g. 'Europe/Stockholm'."
        now = datetime.now(tz)
        return now.strftime(f"**%H:%M:%S** %Z — %A, %B %d %Y (UTC%z)")
    except Exception as e:
        return f"Time lookup failed: {e}"

def tool_web_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=5))
        if not results:
            return "No results found."
        return "\n\n".join(f"**{r['title']}**\n{r['href']}\n{r['body']}" for r in results)
    except Exception as e:
        return f"Search failed: {e}"

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
    suffix = f"\n... ({len(lines)-300} more lines)" if len(lines) > 300 else ""
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
            return f"Blocked: {cmd}"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=REPO_DIR, timeout=15)
    out = (r.stdout + r.stderr).strip()
    return out[:3000] if out else "(no output)"

def tool_commit_push(message: str = "Claude Alt update") -> str:
    _git(["config", "user.name",  "Claude-Alt-Agent"])
    _git(["config", "user.email", "agent@nohands.company"])
    _git(["add", "."])
    c = _git(["commit", "-m", message])
    if c.returncode != 0 and "nothing to commit" in c.stdout:
        return "Nothing to commit."
    if not GITHUB_REPO:
        return "No GITHUB_REPO set, skipped push."
    push_url = GITHUB_REPO.replace("https://github.com", f"https://{GH_TOKEN}@github.com")
    r = subprocess.run(["git", "-C", REPO_DIR, "push", push_url],
                       capture_output=True, text=True,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode != 0:
        raise Exception(f"Push failed: {r.stderr}")
    return f"Committed & pushed: {message}"

TOOL_ICONS = {
    "think": "💭", "get_time": "🕐", "web_search": "🔍",
    "write_file": "📝", "read_file": "📖", "list_files": "📂",
    "delete_file": "🗑️", "run_command": "⚙️", "commit_push": "🚀",
}

def dispatch_tool(action: Dict[str, Any]) -> str:
    kind = action.get("action")
    if kind == "get_time":     return tool_get_time(action.get("timezone", "UTC"))
    if kind == "web_search":   return tool_web_search(action["query"])
    if kind == "write_file":   return tool_write_file(action["path"], action["content"])
    if kind == "read_file":    return tool_read_file(action["path"])
    if kind == "list_files":   return tool_list_files(action.get("pattern", "**/*"))
    if kind == "delete_file":  return tool_delete_file(action["path"])
    if kind == "run_command":  return tool_run_command(action["cmd"])
    if kind == "commit_push":  return tool_commit_push(action.get("message", "Claude Alt update"))
    return f"Unknown action: {kind}"

# ── LLM callers ───────────────────────────────────────────────────────────────
def _parse_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise ValueError("Empty response from model")
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"action": "respond", "content": raw}

def _build_user_content(text: str, files: List[Dict]) -> Any:
    if not files:
        return text
    parts: List[Dict] = []
    text_files = []
    for f in files:
        ftype = f.get("type", "")
        if ftype.startswith("image/"):
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{ftype};base64,{f['content']}"}})
        else:
            text_files.append(f"[File: {f['name']}]\n{f['content']}")
    full_text = ("\n\n".join(text_files) + "\n\n" + text).strip() if text_files else text
    parts.append({"type": "text", "text": full_text})
    return parts

def _call_openai_compat(cfg: Dict, messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv(cfg["env_key"], "") or ("llm7" if cfg.get("keyless") else "")
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    model = _config["model"] or cfg["default_model"]
    payload = {
        "model":       model,
        "messages":    [{"role": "system", "content": TOOLS_DESCRIPTION}] + messages,
        "temperature": _config["temperature"],
        "max_tokens":  4096,
    }
    resp = requests.post(url, json=payload,
                         headers={"Authorization": f"Bearer {api_key}",
                                  "Content-Type": "application/json"},
                         timeout=90)
    resp.raise_for_status()
    return _parse_json(resp.json()["choices"][0]["message"]["content"])

def _call_grok(messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv("GROK_API_KEY", "")
    model = _config["model"] or "grok-3"
    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model,
              "messages": [{"role": "system", "content": TOOLS_DESCRIPTION}] + messages,
              "temperature": _config["temperature"], "max_tokens": 4096},
        timeout=90)
    resp.raise_for_status()
    return _parse_json(resp.json()["choices"][0]["message"]["content"])

def _call_claude_api(messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv("CLAUDE_API_KEY", "")
    model = _config["model"] or "claude-sonnet-4-20250514"
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
        json={"model": model, "system": TOOLS_DESCRIPTION,
              "messages": messages,
              "temperature": _config["temperature"], "max_tokens": 4096},
        timeout=90)
    resp.raise_for_status()
    return _parse_json(resp.json()["content"][0]["text"])

def _call_single(pid: str, messages: List[Dict]) -> Dict[str, Any]:
    cfg = PROVIDERS[pid]
    if cfg["openai_compat"]: return _call_openai_compat(cfg, messages)
    if pid == "grok":        return _call_grok(messages)
    if pid == "claude":      return _call_claude_api(messages)
    raise ValueError(f"No caller for: {pid}")

class AllProvidersExhausted(Exception):
    pass

def call_llm_with_fallback(messages: List[Dict]) -> tuple[Dict[str, Any], str]:
    order = _fallback_order()
    if not order:
        raise AllProvidersExhausted("No providers available (all rate-limited or no keys set).")
    last_err: Optional[Exception] = None
    for pid in order:
        if _is_rate_limited(pid):
            continue
        try:
            return _call_single(pid, messages), pid
        except Exception as e:
            last_err = e
            if _is_rate_limit_error(e):
                _mark_rate_limited(pid)
                print(f"↩️  {pid} rate-limited, trying next…")
            elif isinstance(e, (requests.ConnectionError, requests.Timeout)):
                print(f"⚠️  {pid} connection error, skipping…")
            else:
                print(f"⚠️  {pid} error ({type(e).__name__}: {e}), skipping…")
    raise AllProvidersExhausted(f"All providers exhausted. Last error: {last_err}")

# ── streaming agent ───────────────────────────────────────────────────────────
def stream_agent_task(task: str, history: list,
                      files: list | None = None) -> Iterator[Dict[str, Any]]:
    try:
        setup_repo()
    except Exception as e:
        print(f"setup_repo warning: {e}")

    # Direct answer: bypass LLM for simple queries
    direct = _try_direct_answer(task)
    if direct and not files:
        msgs = list(history)
        msgs.append({"role": "user",      "content": task})
        msgs.append({"role": "assistant", "content": direct})
        yield {"type": "done", "content": direct,
               "provider": "Built-in", "model": "direct", "history": msgs}
        return

    messages: List[Dict] = list(history)
    messages.append({"role": "user", "content": _build_user_content(task, files or [])})

    providers_used: List[str] = []

    for loop_i in range(MAX_LOOP):
        try:
            action, pid = call_llm_with_fallback(messages)
        except AllProvidersExhausted as e:
            print(f"All exhausted, waiting 8s…")
            time.sleep(8)
            try:
                action, pid = call_llm_with_fallback(messages)
            except AllProvidersExhausted:
                yield {"type": "error",
                       "message": str(e) + "\n\nTip: add more provider API keys to avoid rate limits."}
                return

        if pid not in providers_used:
            providers_used.append(pid)
            if len(providers_used) > 1:
                chain = " → ".join(PROVIDERS[p]["label"] for p in providers_used)
                yield {"type": "fallback", "chain": chain}

        kind = action.get("action")

        # ── think: emit reasoning event, feed back, continue ─────────────────
        if kind == "think":
            thought = action.get("thought", "")
            yield {"type": "think", "thought": thought}
            messages.append({"role": "assistant",
                             "content": json.dumps(action, ensure_ascii=False)})
            messages.append({"role": "user", "content": "Continue based on your reasoning."})
            continue

        # ── respond: final answer ─────────────────────────────────────────────
        if kind == "respond":
            final = action.get("content", "")
            messages.append({"role": "assistant", "content": final})
            cfg = PROVIDERS.get(providers_used[-1], {}) if providers_used else {}
            yield {
                "type":     "done",
                "content":  final,
                "provider": cfg.get("label", "?"),
                "model":    _config["model"] or cfg.get("default_model", "?"),
                "history":  messages,
            }
            return

        # ── tool call: execute with one retry on failure ──────────────────────
        icon  = TOOL_ICONS.get(kind, "🔧")
        label = action.get("query") or action.get("path") or action.get("cmd") or \
                action.get("timezone") or kind
        # file content for code viewer (write_file only)
        file_content = action.get("content") if kind == "write_file" else None
        file_path    = action.get("path")    if kind in ("write_file", "read_file") else None

        try:
            result = dispatch_tool(action)
        except Exception as e:
            # Retry once
            print(f"Tool {kind} failed ({e}), retrying…")
            try:
                result = dispatch_tool(action)
            except Exception as e2:
                result = f"Tool failed after retry: {e2}"

        yield {
            "type":         "tool",
            "icon":         icon,
            "action":       kind,
            "label":        str(label)[:120],
            "result":       str(result)[:400],
            "file_path":    file_path,
            "file_content": file_content,
        }

        messages.append({"role": "assistant",
                         "content": json.dumps(action, ensure_ascii=False)})
        messages.append({"role": "user",
                         "content": f"Tool result:\n{result}\n\nContinue."})

    # Hit MAX_LOOP
    final = "Agent reached max tool-call limit."
    messages.append({"role": "assistant", "content": final})
    cfg = PROVIDERS.get(providers_used[-1] if providers_used else "", {})
    yield {"type": "done", "content": final,
           "provider": cfg.get("label", "?"),
           "model": _config["model"] or cfg.get("default_model", "?"),
           "history": messages}

# ── non-streaming wrapper ─────────────────────────────────────────────────────
def run_agent_task(task: str, history: list,
                   files: list | None = None) -> Dict[str, Any]:
    tool_log, fallback_notice = [], ""
    final: Optional[Dict] = None
    for event in stream_agent_task(task, history, files):
        if event["type"] == "tool":
            tool_log.append(f"{event['icon']} **`{event['action']}`** `{event['label']}` → {event['result']}")
        elif event["type"] == "think":
            tool_log.append(f"💭 *{event['thought']}*")
        elif event["type"] == "fallback":
            fallback_notice = f"*↩️ Auto-fallback: {event['chain']}*\n\n"
        elif event["type"] in ("done", "error"):
            final = event
    if not final:
        return {"result": "No response.", "history": history, "provider": "?", "model": "?"}
    if final["type"] == "error":
        return {"result": f"❌ {final['message']}", "history": history, "provider": "none", "model": "none"}
    content = final["content"]
    shown = (fallback_notice
             + ("\n\n".join(tool_log) + "\n\n---\n\n" if tool_log else "")
             + content)
    return {"result": shown, "history": final["history"],
            "provider": final["provider"], "model": final["model"]}

# ── UI helpers ────────────────────────────────────────────────────────────────
def get_providers_list() -> List[Dict]:
    result = []
    for pid, cfg in PROVIDERS.items():
        has_key = _has_key(cfg)
        cooling = _is_rate_limited(pid)
        result.append({
            "id": pid, "label": cfg["label"],
            "model":              _config["model"] or cfg["default_model"],
            "available":          has_key and not cooling,
            "has_key":            has_key,
            "rate_limited":       cooling,
            "cooldown_remaining": max(0, int(_cooldowns.get(pid, 0) - time.time())),
            "keyless":            cfg.get("keyless", False),
            "active":             _config["provider"] in ("auto", pid),
        })
    return result
