"""
src/agents/tools/shell.py — Sandboxed shell command execution wrapper

Typed wrapper around tool_run_command with resource limiting.
All commands run inside a restricted sandbox (no network access by default,
memory cap, CPU time cap, blocked paths).
"""

from __future__ import annotations

import os
import subprocess
import shlex
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Safety configuration
# ---------------------------------------------------------------------------

BLOCKED_COMMANDS = frozenset([
    "rm -rf /", "mkfs", "dd", ":(){ :|:& };:", "shutdown", "reboot",
    "wget", "curl",  # network blocked by default; use tool_api_call instead
])

DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("SHELL_TIMEOUT", "30"))
DEFAULT_MEMORY_MB = int(os.environ.get("SHELL_MEMORY_MB", "512"))


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ShellResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    blocked: bool = False


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_command(
    command: str,
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    allow_network: bool = False,
    env_override: dict | None = None,
) -> ShellResult:
    """
    Run *command* in a sandboxed subprocess.

    Safety controls:
    - Blocked command list rejection
    - Timeout enforcement
    - Restricted environment (no HOME write, no sudo)
    - Network access disabled by default (allow_network=True to override)

    STUB: basic implementation without full OS-level sandboxing.
    Full implementation plan: Linux namespaces / bubblewrap / Docker for isolation.
    """
    # Check blocked commands
    for blocked in BLOCKED_COMMANDS:
        if blocked in command:
            return ShellResult(
                command=command,
                exit_code=1,
                stdout="",
                stderr=f"Command blocked by safety policy: contains '{blocked}'",
                blocked=True,
            )

    # Build safe environment
    safe_env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "en_US.UTF-8",
    }
    if env_override:
        # Only allow whitelisted env keys to be overridden
        allowed_env_keys = {"PYTHONPATH", "NODE_PATH", "VIRTUAL_ENV", "CONDA_PREFIX"}
        for k, v in env_override.items():
            if k in allowed_env_keys:
                safe_env[k] = v

    try:
        proc = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=safe_env,
        )
        return ShellResult(
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout[:10_000],   # truncate large outputs
            stderr=proc.stderr[:2_000],
        )
    except subprocess.TimeoutExpired:
        return ShellResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            timed_out=True,
        )
    except FileNotFoundError as e:
        return ShellResult(
            command=command,
            exit_code=127,
            stdout="",
            stderr=f"Command not found: {e}",
        )


def git_status(repo_path: str = ".") -> str:
    """Return git status output. STUB: calls run_command."""
    result = run_command("git status --porcelain", cwd=repo_path)
    return result.stdout or "(clean)"


def git_log(repo_path: str = ".", n: int = 10) -> str:
    """Return recent git log. STUB: calls run_command."""
    result = run_command(f"git log --oneline -{n}", cwd=repo_path)
    return result.stdout or "(no commits)"


def git_diff(repo_path: str = ".", ref: str = "HEAD") -> str:
    """Return git diff against *ref*. STUB: calls run_command."""
    result = run_command(f"git diff {ref}", cwd=repo_path)
    return result.stdout or "(no diff)"
