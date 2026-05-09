from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from urllib import request


def _chat_completion(base_url: str, model: str, prompt: str, max_tokens: int = 300) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    return str(body.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()


def generate_test_fix_loop(
    *,
    base_url: str,
    model: str,
    task_prompt: str,
    target_file: Path,
    test_command: str,
    max_rounds: int = 3,
) -> dict[str, Any]:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    rounds: list[dict[str, Any]] = []

    for i in range(1, max_rounds + 1):
        if i == 1:
            prompt = (
                "Generate only code for the requested task. No markdown.\\n"
                f"Task: {task_prompt}\\n"
            )
        else:
            prev = rounds[-1]
            prompt = (
                "You are fixing code after failed tests. Return only full corrected code. No markdown.\\n"
                f"Task: {task_prompt}\\n"
                f"Previous stderr:\\n{prev.get('stderr', '')[:5000]}\\n"
            )

        candidate = _chat_completion(base_url=base_url, model=model, prompt=prompt)
        target_file.write_text(candidate + "\n", encoding="utf-8")

        proc = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        step = {
            "round": i,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "passed": proc.returncode == 0,
        }
        rounds.append(step)
        if step["passed"]:
            break

    return {
        "model": model,
        "target_file": str(target_file),
        "rounds": rounds,
        "success": any(bool(r.get("passed")) for r in rounds),
        "attempts": len(rounds),
    }
