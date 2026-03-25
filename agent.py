import os
import json
import requests
import subprocess
from typing import Dict, Any

GROK_API_KEY = os.getenv("GROK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PROVIDER = os.getenv("PROVIDER", "grok").lower()

REPO_DIR = "/tmp/repo"


def setup_repo() -> None:
    """Clone or reuse the repo with proper token auth"""
    if os.path.exists(REPO_DIR):
        print("✅ Repo already cloned")
        return

    if not GITHUB_REPO:
        raise Exception("GITHUB_REPO env var is missing")

    clone_url = GITHUB_REPO
    if GITHUB_TOKEN and clone_url.startswith("https://github.com"):
        clone_url = clone_url.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")

    print("Cloning repo...")
    result = subprocess.run(
        ["git", "clone", clone_url, REPO_DIR],
        capture_output=True, text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    )

    if result.returncode != 0:
        raise Exception(f"Git clone failed: {result.stderr}")

    print("✅ Repo cloned successfully")


def run_command_in_repo(command: str) -> str:
    """Run any shell command inside the repo and return output"""
    try:
        result = subprocess.run(
            command, shell=True, cwd=REPO_DIR,
            capture_output=True, text=True, timeout=30
        )
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    except Exception as e:
        return f"Command failed: {str(e)}"


def read_file(path: str) -> str:
    """Read a file from the repo"""
    full_path = os.path.join(REPO_DIR, path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"File not found: {path}"


def write_file(path: str, content: str) -> str:
    """Write content to a file"""
    full_path = os.path.join(REPO_DIR, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"✅ Wrote {path}"


def commit_and_push() -> str:
    """Commit and push changes"""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    # Set git identity
    subprocess.run(["git", "-C", REPO_DIR, "config", "user.name", "Claude-Alt-Agent"], check=True, env=env)
    subprocess.run(["git", "-C", REPO_DIR, "config", "user.email", "agent@nohands.company"], check=True, env=env)

    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True, env=env)

    # Commit (safe if nothing changed)
    subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", "Claude Alt update"], check=False, env=env)

    # Push with token
    push_url = GITHUB_REPO
    if GITHUB_TOKEN and push_url.startswith("https://github.com"):
        push_url = push_url.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")

    result = subprocess.run(["git", "-C", REPO_DIR, "push", push_url],
                            capture_output=True, text=True, env=env)

    if result.returncode != 0:
        raise Exception(f"Push failed: {result.stderr}")
    return "✅ Changes pushed to GitHub"


def call_grok(task: str) -> Dict[str, Any]:
    """Call Grok and force JSON action format"""
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-3",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Claude Code — a self-hosted coding agent.\n"
                    "You can: read files, edit files, run commands, or just respond.\n"
                    "ALWAYS reply with ONLY valid JSON using one of these actions:\n"
                    '1. {"action": "respond", "content": "your explanation here"}\n'
                    '2. {"action": "read_file", "path": "main.py"}\n'
                    '3. {"action": "write_file", "path": "file.py", "content": "full code here"}\n'
                    '4. {"action": "run_command", "command": "ls -la"}\n'
                    "Never add extra text outside the JSON."
                )
            },
            {"role": "user", "content": task}
        ],
        "temperature": 0.2,
        "max_tokens": 4096
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()

    # Clean possible markdown
    if content.startswith("```json"): content = content.split("```json")[1].split("```")[0].strip()
    elif content.startswith("```"): content = content.split("```")[1].strip()

    return json.loads(content)


def run_agent_task(task: str) -> Dict[str, Any]:
    try:
        setup_repo()

        action = call_grok(task)
        print("Action received:", action)

        if action["action"] == "respond":
            return {"result": action.get("content", "No content")}

        elif action["action"] == "read_file":
            content = read_file(action["path"])
            return {"result": f"📄 File content of {action['path']}:\n\n{content}"}

        elif action["action"] == "write_file":
            msg = write_file(action["path"], action.get("content", ""))
            commit_and_push()
            return {"result": f"{msg}\n✅ Committed & pushed!"}

        elif action["action"] == "run_command":
            output = run_command_in_repo(action["command"])
            return {"result": f"💻 Command output:\n{output}"}

        else:
            return {"error": "Unknown action from model"}

    except Exception as e:
        return {"error": str(e)}
