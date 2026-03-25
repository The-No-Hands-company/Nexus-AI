import os
import json
import requests
import subprocess
from typing import Dict, Any

# Environment variables
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")

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

    # Commit (ignore if nothing to commit)
    commit_result = subprocess.run(
        ["git", "-C", REPO_DIR, "commit", "-m", "AI update"],
        capture_output=True, text=True, env=env
    )
    print("Commit output:", commit_result.stdout, commit_result.stderr)

    # Push
    push_result = subprocess.run(
        ["git", "-C", REPO_DIR, "push"],
        capture_output=True, text=True, env=env
    )
    if push_result.returncode != 0:
        raise Exception(f"Git push failed: {push_result.stderr}")

    print("Successfully pushed to GitHub!")


def run_agent_task(task: str) -> Dict[str, Any]:
    try:
        setup_repo()

        print("STEP 2: calling DeepSeek")

        url = "https://api.deepseek.com/chat/completions"   # ← without /v1

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
                        "You are a helpful coding assistant.\n"
                        "You MUST respond with **ONLY** valid JSON object.\n"
                        "No extra text, no markdown, no explanations.\n"
                        "Format exactly:\n"
                        '{"action": "write_file", "path": "folder/file.py", "content": "the full code here"}'
                    )
                },
                {"role": "user", "content": task}
            ],
            "temperature": 0.3,      # lower = more consistent JSON
            "max_tokens": 4096
        }

        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        # This will raise if status is not 2xx (very important!)
        response.raise_for_status()

        data = response.json()

        print("STEP 3: raw response received")

        # Safe extraction
        if "choices" not in data or not data["choices"]:
            error_msg = data.get("error", {}).get("message", str(data))
            return {"error": f"DeepSeek API error: {error_msg}"}

        content = data["choices"][0]["message"]["content"].strip()

        # Try to clean possible markdown/code fences the model sometimes adds
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].strip()

        action = json.loads(content)

        if action.get("action") == "write_file":
            write_file(action["path"], action["content"])
            commit_and_push()
            return {
                "status": "success",
                "message": f"File {action['path']} written and pushed to GitHub"
            }

        return {"error": "Unknown action", "raw_action": action}

    except json.JSONDecodeError as e:
        return {
            "error": "Model did not return valid JSON",
            "raw_content": content if 'content' in locals() else "N/A"
        }
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP error {response.status_code}: {response.text[:500]}"}
    except Exception as e:
        return {"error": str(e)}
