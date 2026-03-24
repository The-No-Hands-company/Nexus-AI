import os
import requests
import subprocess
import json

print("STEP 1: setup_repo")
setup_repo()

print("STEP 2: calling AI")
response = requests.post(...)

print("STEP 3: parsing response")

print("STEP 4: writing file")

print("STEP 5: pushing to git")
commit_and_push()

print("DONE")

# Environment variables
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GITHUB_REPO = os.getenv("GITHUB_REPO")

REPO_DIR = "/tmp/repo"


# Clone repo if not already cloned
def setup_repo():
    if not os.path.exists(REPO_DIR):
        subprocess.run([
            "git", "clone",
            GITHUB_REPO,
            REPO_DIR
        ], check=True)


# Write or create a file
def write_file(path, content):
    full_path = os.path.join(REPO_DIR, path)

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w") as f:
        f.write(content)


# Commit and push changes
def commit_and_push():
    subprocess.run(["git", "-C", REPO_DIR, "add", "."], check=True)
    subprocess.run(
        ["git", "-C", REPO_DIR, "commit", "-m", "AI update"],
        check=False  # avoids crash if nothing changed
    )
    subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)


# Main AI function
def run_agent_task(task: str):
    setup_repo()

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
                        "You are an AI that outputs ONLY valid JSON. "
                        "Supported actions:\n"
                        "{ \"action\": \"write_file\", \"path\": \"file.py\", \"content\": \"code here\" }"
                    )
                },
                {"role": "user", "content": task}
            ]
        }
    )

    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]

        action = json.loads(content)

        if action["action"] == "write_file":
            write_file(action["path"], action["content"])
            commit_and_push()
            return {"status": "file written and pushed"}

        return {"error": "Unknown action", "raw": action}

    except Exception as e:
        return {
            "error": str(e),
            "raw_response": data
        }
