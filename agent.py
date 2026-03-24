import os
import subprocess

REPO_PATH = "./repo"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")

def auth_repo_url():
    return GITHUB_REPO.replace(
        "https://",
        f"https://{GITHUB_TOKEN}@"
    )

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr

def clone_repo():
    if not os.path.exists(REPO_PATH):
        return run(f"git clone {auth_repo_url()} {REPO_PATH}")
    return "Repo already exists"

def commit_and_push():
    logs = []
    logs.append(run(f"git -C {REPO_PATH} add ."))
    logs.append(run(f'git -C {REPO_PATH} commit -m "AI update"'))
    logs.append(run(f"git -C {REPO_PATH} push {auth_repo_url()}"))
    return logs
