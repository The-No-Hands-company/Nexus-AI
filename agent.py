import os
import subprocess

REPO_DIR = "/tmp/repo"

def setup_repo():
    if not os.path.exists(REPO_DIR):
        subprocess.run([
            "git", "clone",
            os.getenv("GITHUB_REPO"),
            REPO_DIR
        ])

def write_file(path, content):
    full_path = os.path.join(REPO_DIR, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w") as f:
        f.write(content)

def commit_and_push():
    subprocess.run(["git", "-C", REPO_DIR, "add", "."])
    subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", "AI update"])
    subprocess.run(["git", "-C", REPO_DIR, "push"])
