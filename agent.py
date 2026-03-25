import os
import json
import requests
import subprocess
from typing import Dict, Any

# Environment variables
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")
PROVIDER = os.getenv("PROVIDER", "grok").lower()   # default to grok for now (cheaper + more reliable free tier)

REPO_DIR = "/tmp/repo"


def setup_repo() -> None:
    print("STEP 1: setup_repo")
    if os.path.exists(REPO_DIR):
        print("Repo already exists, skipping clone")
        return

    if not GITHUB_REPO:
        raise Exception("GITHUB_REPO environment variable is not set")

    result = subprocess.run(
        ["git", "clone", GITHUB_REPO, REPO_DIR],
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
    print("STEP 5: committing and pushing to git")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True, env=env)

    commit_result = subprocess.run(
        ["git", "-C", REPO_DIR, "commit", "-m", "AI update"],
        capture_output=True, text=True, env=env
    )
    print("Commit output:", commit_result.stdout, commit_result.stderr)

    push_result = subprocess.run(
        ["git", "-C", REPO_DIR, "push"],
        capture_output=True, text=True, env=env
    )
    if push_result.returncode != 0:
        raise Exception(f"Git push failed: {push_result.stderr}")

    print("Successfully pushed to GitHub!")


def call_deepseek(task: str) -> Dict[str, Any]:
    if not DEEPSEEK_API_KEY:
        return {"error": "DEEPSEEK_API_KEY is not set"}

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise coding assistant.\n"
                    "Respond with **ONLY** a valid JSON object. No extra text, no markdown, no explanations.\n"
                    'Example: {"action": "write_file", "path": "README.md", "content": "Full file content here"}'
                )
            },
            {"role": "user", "content": task}
        ],
        "temperature": 0.2,
        "max_tokens": 4096
    }

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()

    content = data["choices"][0]["message"]["content"].strip()

    # Clean possible code fences
    if content.startswith("```json"): content = content.split("```json", 1)[1].split("```", 1)[0].strip()
    elif content.startswith("```"): content = content.split("```", 1)[1].strip()

    action = json.loads(content)
    return action


def call_grok(task: str) -> Dict[str, Any]:
    if not GROK_API_KEY:
        return {"error": "GROK_API_KEY is not set"}

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-3",          # or "grok-3-mini" if you want faster/cheaper
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise coding assistant.\n"
                    "Respond with **ONLY** a valid JSON object. No extra text, no markdown, no explanations.\n"
                    'Example: {"action": "write_file", "path": "README.md", "content": "Full file content here"}'
                )
            },
            {"role": "user", "content": task}
        ],
        "temperature": 0.2,
        "max_tokens": 4096
    }

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()

    content = data["choices"][0]["message"]["content"].strip()

    # Clean possible code fences
    if content.startswith("```json"): content = content.split("```json", 1)[1].split("```", 1)[0].strip()
    elif content.startswith("```"): content = content.split("```", 1)[1].strip()

    action = json.loads(content)
    return action


def run_agent_task(task: str) -> Dict[str, Any]:
    try:
        setup_repo()

        print(f"STEP 2: calling {PROVIDER.upper()}")

        if PROVIDER == "deepseek":
            action = call_deepseek(task)
        else:  # default to grok
            action = call_grok(task)

        print("STEP 3: parsed action:", action)

        if action.get("action") == "write_file":
            write_file(action["path"], action["content"])
            commit_and_push()
            return {
                "status": "success",
                "message": f"File '{action.get('path')}' written and pushed to GitHub"
            }

        return {"error": "Unknown action", "raw_action": action}

    except json.JSONDecodeError as e:
        return {"error": "Model did not return valid JSON", "details": str(e)}
    except requests.exceptions.HTTPError as e:
        error_text = response.text if 'response' in locals() else str(e)
        return {"error": f"HTTP error {getattr(response, 'status_code', 'unknown')}: {error_text[:600]}"}
    except Exception as e:
        return {"error": str(e)}
