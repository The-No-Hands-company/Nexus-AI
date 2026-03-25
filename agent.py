import os
import json
import requests
import subprocess
from typing import Dict, Any

GROK_API_KEY = os.getenv("GROK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GH_TOKEN = os.getenv("GH_TOKEN")          # ← Use GH_TOKEN instead of GITHUB_TOKEN
PROVIDER = os.getenv("PROVIDER", "grok").lower()

REPO_DIR = "/tmp/repo"


def setup_repo() -> None:
    print("=== STEP 1: setup_repo ===")
    if os.path.exists(REPO_DIR):
        print("✅ Repo already exists")
        return

    if not GITHUB_REPO or not GH_TOKEN:
        raise Exception(f"Missing env vars. GITHUB_REPO={bool(GITHUB_REPO)}, GH_TOKEN={bool(GH_TOKEN)}")

    auth_url = GITHUB_REPO.replace("https://github.com", f"https://{GH_TOKEN}@github.com")

    print("Cloning with token...")

    result = subprocess.run(
        ["git", "clone", auth_url, REPO_DIR],
        capture_output=True, text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    )

    print("GIT CLONE STDOUT:", result.stdout)
    print("GIT CLONE STDERR:", result.stderr)

    if result.returncode != 0:
        raise Exception(f"Git clone failed: {result.stderr}")


def write_file(path: str, content: str) -> str:
    full_path = os.path.join(REPO_DIR, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"✅ Wrote {path}"


def commit_and_push() -> str:
    print("=== STEP 5: commit & push ===")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    subprocess.run(["git", "-C", REPO_DIR, "config", "user.name", "Claude-Alt-Agent"], check=True, env=env)
    subprocess.run(["git", "-C", REPO_DIR, "config", "user.email", "agent@nohands.company"], check=True, env=env)

    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", "Claude Alt update"], check=False, env=env)

    push_url = GITHUB_REPO.replace("https://github.com", f"https://{GH_TOKEN}@github.com")

    result = subprocess.run(["git", "-C", REPO_DIR, "push", push_url],
                            capture_output=True, text=True, env=env)

    if result.returncode != 0:
        raise Exception(f"Push failed: {result.stderr}")

    print("✅ Pushed successfully!")
    return "Changes pushed to GitHub"


def call_grok(task: str) -> Dict[str, Any]:
    if not GROK_API_KEY:
        return {"error": "GROK_API_KEY missing"}

    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-3",
        "messages": [
            {"role": "system", "content": "Reply ONLY with valid JSON: {\"action\": \"respond\", \"content\": \"...\"} or {\"action\": \"write_file\", \"path\": \"file.md\", \"content\": \"...\"}"},
            {"role": "user", "content": task}
        ],
        "temperature": 0.2,
        "max_tokens": 2048
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.split("```", 2)[1].strip()

    return json.loads(content)


def run_agent_task(task: str) -> Dict[str, Any]:
    try:
        setup_repo()
        action = call_grok(task)
        print("Action:", action)

        if action.get("action") == "respond":
            return {"result": action.get("content")}

        elif action.get("action") == "write_file":
            msg = write_file(action.get("path", "new_file.txt"), action.get("content", ""))
            commit_and_push()
            return {"result": f"{msg}\n✅ Committed & pushed!"}

        return {"result": "Action received"}

    except Exception as e:
        return {"error": str(e)}
