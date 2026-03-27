import os
import json
import glob
import requests
import subprocess
from typing import Dict, Any, List

# ── env ───────────────────────────────────────────────────────────────────────
GROK_API_KEY   = os.getenv("GROK_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
GITHUB_REPO    = os.getenv("GITHUB_REPO")
GH_TOKEN       = os.getenv("GH_TOKEN")
PROVIDER       = os.getenv("PROVIDER", "grok").lower()   # "grok" | "claude"
REPO_DIR       = os.getenv("REPO_DIR", "/tmp/repo")

MAX_LOOP = 6   # max tool calls per request

# ── tool schema ───────────────────────────────────────────────────────────────
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
    return subprocess.run(["git", "-C", REPO_DIR] + args,
                          capture_output=True, text=True, env=env)


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
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                            cwd=REPO_DIR, timeout=15)
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
    result = subprocess.run(["git", "-C", REPO_DIR, "push", push_url],
                            capture_output=True, text=True, env=env)
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


def call_grok(messages: List[Dict]) -> Dict[str, Any]:
    if not GROK_API_KEY:
        return {"action": "respond", "content": "GROK_API_KEY is not set."}
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-3",
        "messages": [{"role": "system", "content": TOOLS_DESCRIPTION}] + messages,
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    return _parse_json(raw)


def call_claude(messages: List[Dict]) -> Dict[str, Any]:
    if not CLAUDE_API_KEY:
        return {"action": "respond", "content": "CLAUDE_API_KEY is not set."}
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-20250514",
        "system": TOOLS_DESCRIPTION,
        "messages": messages,
        "max_tokens": 4096,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"]
    return _parse_json(raw)


def call_llm(messages: List[Dict]) -> Dict[str, Any]:
    if PROVIDER == "claude":
        return call_claude(messages)
    return call_grok(messages)


# ── agent loop ────────────────────────────────────────────────────────────────
def run_agent_task(task: str, history: list | None = None) -> Dict[str, Any]:
    """
    history: list of {"role": "user"|"assistant", "content": str}
    Returns: {"result": str, "history": [...], "provider": str}
    """
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

        # Tool call — execute and feed result back
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

    return {
        "result":   shown,
        "history":  messages,
        "provider": PROVIDER,
    }
