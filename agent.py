import os
import json
import requests
import subprocess
from typing import Dict, Any

# Load environment variables
GROK_API_KEY = os.getenv("GROK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PROVIDER = os.getenv("PROVIDER", "grok").lower()

REPO_DIR = "/tmp/repo"


def setup_repo() -> None:
    print("=== STEP 1: setup_repo ===")
    if os.path.exists(REPO_DIR):
        print("✅ Repo already cloned, skipping")
        return

    if not GITHUB_REPO or not GITHUB_TOKEN:
        raise Exception(f"Missing env vars. GITHUB_REPO={bool(GITHUB_REPO)}, GITHUB_TOKEN={bool(GITHUB_TOKEN)}")

    # Force token into the URL (this is the reliable way)
    auth_url = GITHUB_REPO.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")

    print("Cloning with embedded token...")

    result = subprocess.run(
        ["git", "clone", auth_url, REPO_DIR],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    )

    print("GIT CLONE STDOUT:", result.stdout)
    print("GIT CLONE STDERR:", result.stderr)

    if result.returncode != 0:
        raise Exception(f"Git clone failed: {result.stderr.strip()}")


def write_file(path: str, content: str) -> str:
    print(f"Writing file: {path}")
    full_path = os.path.join(REPO_DIR, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"✅ Wrote {path}"


def commit_and_push() -> str:
    print("=== STEP 5: commit_and_push ===")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    subprocess.run(["git", "-C", REPO_DIR, "config", "user.name", "Claude-Alt-Agent"], check=True, env=env)
    subprocess.run(["git", "-C", REPO_DIR, "config", "user.email", "agent@nohands.company"], check=True, env=env)

    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", "Claude Alt update"], check=False, env=env)

    push_url = GITHUB_REPO.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")

    result = subprocess.run(
        ["git", "-C", REPO_DIR, "push", push_url],
        capture_output=True, text=True, env=env
    )

    if result.returncode != 0:
        raise Exception(f"Git push failed: {result.stderr.strip()}")

    print("✅ Successfully pushed to GitHub!")
    return "Changes pushed successfully"


def call_grok(task: str) -> Dict[str, Any]:
    if not GROK_API_KEY:
        return {"error": "GROK_API_KEY is not set"}

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-3",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful coding agent.\n"
                    "Always respond with ONLY valid JSON, no extra text:\n"
                    '{"action": "respond", "content": "your answer"}\n'
                    'or {"action": "write_file", "path": "filename.txt", "content": "file content here"}'
                )
            },
            {"role": "user", "content": task}
        ],
        "temperature": 0.2,
        "max_tokens": 2048
    }

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.split("```", 2)[1].strip()

    return json.loads(content)


def run_agent_task(task: str) -> Dict[str, Any]:
    try:
        setup_repo()
        action = call_grok(task)
        print("Action from Grok:", action)

        if action.get("action") == "respond":
            return {"result": action.get("content", "Task completed")}

        elif action.get("action") == "write_file":
            msg = write_file(action.get("path", "new_file.txt"), action.get("content", ""))
            commit_and_push()
            return {"result": f"{msg}\n✅ Committed & pushed to GitHub"}

        return {"result": f"Received action: {action.get('action')}"}

    except Exception as e:
        return {"error": str(e)}
