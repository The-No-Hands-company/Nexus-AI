import os
import subprocess

REPO_PATH = "./repo"

def ensure_repo():
    if not os.path.exists(REPO_PATH):
        os.makedirs(REPO_PATH)

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr

def clone_repo(repo_url):
    return run(f"git clone {repo_url} {REPO_PATH}")

def commit_and_push():
    logs = []
    logs.append(run(f"git -C {REPO_PATH} add ."))
    logs.append(run(f'git -C {REPO_PATH} commit -m "AI update"'))
    logs.append(run(f"git -C {REPO_PATH} push"))
    return logs

def write_file(path, content):
    full_path = os.path.join(REPO_PATH, path)

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)

    return f"Written {path}"

def run_agent_task(task):
    ensure_repo()
    logs = []

    # VERY BASIC logic (we improve later)
    if "clone" in task.lower():
        logs.append(clone_repo("https://github.com/The-No-Hands-company/Claude-alt.git"))

    elif "hello" in task.lower():
        logs.append(write_file("hello.py", 'print("Hello from your AI agent")'))
        logs.extend(commit_and_push())

    else:
        logs.append("Task not understood yet")

    return logs
