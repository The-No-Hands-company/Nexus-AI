import os
import requests
import subprocess
import json

# Environment variables
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")

REPO_DIR = "/tmp/repo"


# Clone repo if not already cloned
def setup_repo():
    print("STEP 1: setup_repo")

    if not os.path.exists(REPO_DIR):
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


# Write or create a file
def write_file(path, content):
    print("STEP 4: writing file")

    full_path = os.path.join(REPO_DIR, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w") as f:
        f.write(content)


# Commit and push changes
def commit_and_push():
    print("STEP 5: pushing to git")

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True, env=env)

    subprocess.run(
        ["git", "-C", REPO_DIR, "commit", "-m", "AI update"],
        check=False,
        env=env
    )

    subprocess.run(
        ["git", "-C", REPO_DIR, "push"],
        check=True,
        env=env
    )


# Main AI function
def run_agent_task(task: str):
    try:
        setup_repo()

        print("STEP 2: calling AI")

        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You MUST respond ONLY with valid JSON.\n"
                            "Format:\n"
                            "{ \"action\": \"write_file\", \"path\": \"file.py\", \"content\": \"code here\" }"
                        )
                    },
                    {"role": "user", "content": task}
                ]
            },
            timeout=30
        )

        print("STEP 3: parsing response")

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        action = json.loads(content)

        if action["action"] == "write_file":
            write_file(action["path"], action["content"])
            commit_and_push()
            return {"status": "file written and pushed"}

        return {"error": "Unknown action", "raw": action}

    except Exception as e:
        return {
            "error": str(e)
        }
