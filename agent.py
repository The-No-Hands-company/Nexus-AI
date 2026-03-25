import os
import json
import requests
import subprocess
from typing import Dict, Any

# Environment variables
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")          # ← Add this in Railway
PROVIDER = os.getenv("PROVIDER", "grok").lower()

REPO_DIR = "/tmp/repo"


def setup_repo() -> None:
    print("STEP 1: setup_repo")
    if os.path.exists(REPO_DIR):
        print("Repo already exists, skipping clone")
        return

    if not GITHUB_REPO:
        raise Exception("GITHUB_REPO is not set")

    # Build authenticated clone URL
    clone_url = GITHUB_REPO
    if GITHUB_TOKEN:
        # Convert to https://TOKEN@github.com/...
        if clone_url.startswith("https://github.com"):
            clone_url = clone_url.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")

    print("Cloning with token (token hidden in logs)")

    result = subprocess.run(
        ["git", "clone", clone_url, REPO_DIR],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    )

    print("GIT STDOUT:", result.stdout)
    print("GIT STDERR:", result.stderr)

    if result.returncode != 0:
        raise Exception(f"Git clone failed: {result.stderr}")


def write_file(path: str, content: str) -> None:
    print(f"STEP 4: writing file {path}")
    full_path = os.path.join(REPO_DIR, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)


def commit_and_push() -> None:
    print("STEP 5: committing and pushing")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    # Set git identity (required on fresh clone)
    subprocess.run(["git", "-C", REPO_DIR, "config", "user.name", "Claude-Alt-Agent"], check=True, env=env)
    subprocess.run(["git", "-C", REPO_DIR, "config", "user.email", "agent@nohands.company"], check=True, env=env)

    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True, env=env)

    commit_result = subprocess.run(
        ["git", "-C", REPO_DIR, "commit", "-m", "AI update"],
        capture_output=True, text=True, env=env
    )
    print("Commit:", commit_result.stdout or commit_result.stderr)

    # Push with token
    push_url = GITHUB_REPO
    if GITHUB_TOKEN and "github.com" in push_url:
        push_url = push_url.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")

    push_result = subprocess.run(
        ["git", "-C", REPO_DIR, "push", push_url],
        capture_output=True, text=True, env=env
    )

    if push_result.returncode != 0:
        raise Exception(f"Git push failed: {push_result.stderr}")

    print("✅ Successfully pushed to GitHub!")


# ================== AI Call Functions (same as before) ==================
def call_grok(task: str) -> Dict[str, Any]:   # I'll use Grok as default for now
    if not GROK_API_KEY:
        return {"error": "GROK_API_KEY not set"}
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-3",
        "messages": [
            {"role": "system", "content": "Respond ONLY with valid JSON: {\"action\": \"write_file\", \"path\": \"file.md\", \"content\": \"...\"}"},
            {"role": "user", "content": task}
        ],
        "temperature": 0.2,
        "max_tokens": 2048
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()
    # Clean JSON if needed
    if content.startswith("```"): 
        content = content.split("```", 2)[1].strip()
    action = json.loads(content)
    return action


def run_agent_task(task: str) -> Dict[str, Any]:
    try:
        setup_repo()
        print(f"STEP 2: calling {PROVIDER.upper()}")

        if PROVIDER == "deepseek":
            # Add call_deepseek similarly if needed
            action = call_grok(task)  # fallback
        else:
            action = call_grok(task)

        print("STEP 3: action received:", action)

        if action.get("action") == "write_file":
            write_file(action["path"], action.get("content", ""))
            commit_and_push()
            return {"status": "success", "message": f"Updated {action.get('path')}"}

        return {"error": "Unknown action", "raw": action}

    except Exception as e:
        return {"error": str(e)}


# For completeness, you can add call_deepseek the same way as before if you want to switch later.
