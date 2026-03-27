import os
import json
import glob
import requests
import subprocess
from typing import Dict, Any, List

# ── env ───────────────────────────────────────────────────────────────────────
PROVIDER = os.getenv("PROVIDER", "groq").lower()
REPO_DIR = os.getenv("REPO_DIR", "/tmp/repo")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GH_TOKEN    = os.getenv("GH_TOKEN")
MAX_LOOP    = 6

# ── provider registry ─────────────────────────────────────────────────────────
# All entries with "openai_compat: True" share the same caller — just swap
# base_url + api_key + model.  Claude and Grok get their own callers.
PROVIDERS = {
    # ── OpenAI-compatible (free permanent tiers) ──────────────────────────────
    "groq": {
        "label":          "Groq",
        "base_url":       "https://api.groq.com/openai/v1",
        "env_key":        "GROQ_API_KEY",
        "default_model":  "llama-3.3-70b-versatile",
        "openai_compat":  True,
    },
    "cerebras": {
        "label":          "Cerebras",
        "base_url":       "https://api.cerebras.ai/v1",
        "env_key":        "CEREBRAS_API_KEY",
        "default_model":  "llama-3.3-70b",
        "openai_compat":  True,
    },
    "mistral": {
        "label":          "Mistral AI",
        "base_url":       "https://api.mistral.ai/v1",
        "env_key":        "MISTRAL_API_KEY",
        "default_model":  "mistral-small-latest",
        "openai_compat":  True,
    },
    "openrouter": {
        "label":          "OpenRouter",
        "base_url":       "https://openrouter.ai/api/v1",
        "env_key":        "OPENROUTER_API_KEY",
        "default_model":  "meta-llama/llama-3.3-70b-instruct:free",
        "openai_compat":  True,
    },
    "nvidia": {
        "label":          "NVIDIA NIM",
        "base_url":       "https://integrate.api.nvidia.com/v1",
        "env_key":        "NVIDIA_API_KEY",
        "default_model":  "meta/llama-3.3-70b-instruct",
        "openai_compat":  True,
    },
    "gemini": {
        "label":          "Google Gemini",
        # Google exposes an OpenAI-compat shim at this endpoint
        "base_url":       "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key":        "GEMINI_API_KEY",
        "default_model":  "gemini-2.0-flash",
        "openai_compat":  True,
    },
    "llm7": {
        "label":          "LLM7.io",
        "base_url":       "https://api.llm7.io/v1",
        "env_key":        "LLM7_API_KEY",   # free tier works without a key (use "llm7")
        "default_model":  "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "openai_compat":  True,
    },
    "cohere": {
        "label":          "Cohere",
        "base_url":       "https://api.cohere.com/compatibility/v1",
        "env_key":        "COHERE_API_KEY",
        "default_model":  "command-r-plus",
        "openai_compat":  True,
    },
    "github_models": {
        "label":          "GitHub Models",
        "base_url":       "https://models.inference.ai.azure.com",
        "env_key":        "GITHUB_MODELS_TOKEN",   # GitHub PAT with model access
        "default_model":  "meta-llama/Llama-3.3-70B-Instruct",
        "openai_compat":  True,
    },
    # ── Non-OpenAI-compat (custom callers) ────────────────────────────────────
    "grok": {
        "label":          "Grok (xAI)",
        "env_key":        "GROK_API_KEY",
        "default_model":  "grok-3",
        "openai_compat":  False,
    },
    "claude": {
        "label":          "Claude (Anthropic)",
        "env_key":        "CLAUDE_API_KEY",
        "default_model":  "claude-sonnet-4-20250514",
        "openai_compat":  False,
    },
}

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
    result = subprocess.run(["git", "-C", REPO_DIR, "push", push_url], capture_output=True, text=True, env=env)
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


# ── LLM callers ───────────────────────────────────────────────────────────────
def _parse_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def call_openai_compat(cfg: dict, messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv(cfg["env_key"], "")
    # LLM7 works without a key; send a placeholder so the header is valid
    if not api_key:
        if cfg.get("label") == "LLM7.io":
            api_key = "llm7"
        else:
            return {"action": "respond", "content": f"{cfg['env_key']} is not set."}

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


def call_grok(messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv("GROK_API_KEY", "")
    if not api_key:
        return {"action": "respond", "content": "GROK_API_KEY is not set."}
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


def call_claude(messages: List[Dict]) -> Dict[str, Any]:
    api_key = os.getenv("CLAUDE_API_KEY", "")
    if not api_key:
        return {"action": "respond", "content": "CLAUDE_API_KEY is not set."}
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }
    payload = {
        "model":     os.getenv("LLM_MODEL", "claude-sonnet-4-20250514"),
        "system":    TOOLS_DESCRIPTION,
        "messages":  messages,
        "max_tokens": 4096,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"]
    return _parse_json(raw)


def call_llm(messages: List[Dict]) -> Dict[str, Any]:
    cfg = PROVIDERS.get(PROVIDER)
    if not cfg:
        return {"action": "respond", "content": f"Unknown provider: {PROVIDER}"}
    if cfg["openai_compat"]:
        return call_openai_compat(cfg, messages)
    if PROVIDER == "grok":
        return call_grok(messages)
    if PROVIDER == "claude":
        return call_claude(messages)
    return {"action": "respond", "content": f"No caller implemented for: {PROVIDER}"}


# ── agent loop ────────────────────────────────────────────────────────────────
def run_agent_task(task: str, history: list | None = None) -> Dict[str, Any]:
    try:
        setup_repo()
    except Exception as e:
        print(f"setup_repo warning: {e}")

    messages: List[Dict] = list(history or [])
    messages.append({"role": "user", "content": task})

    tool_log: List[str] = []
    final_response = ""

    for _ in range(MAX_LOOP):
        action = call_llm(messages)

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

    cfg = PROVIDERS.get(PROVIDER, {})
    return {
        "result":   shown,
        "history":  messages,
        "provider": cfg.get("label", PROVIDER),
        "model":    os.getenv("LLM_MODEL", cfg.get("default_model", "?")),
    }


def get_providers_list() -> List[Dict]:
    """Returns provider info for the UI — marks which ones have their key set."""
    result = []
    for key, cfg in PROVIDERS.items():
        api_key = os.getenv(cfg["env_key"], "")
        # LLM7 is keyless
        available = bool(api_key) or cfg.get("label") == "LLM7.io"
        result.append({
            "id":        key,
            "label":     cfg["label"],
            "model":     os.getenv("LLM_MODEL", cfg["default_model"]),
            "available": available,
            "active":    key == PROVIDER,
        })
    return result
