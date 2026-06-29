"""Autonomous loop state management for Nexus AI.

The loop system persists progress across context window resets, crashes,
and token limit exhaustion. The file system is the memory.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


class LoopState:
    """Persistent state for autonomous development loops.

    Writes to LOOP_STATE.md in the project root. Survives all failures.
    """

    def __init__(self, state_file: str | Path | None = None):
        if state_file is None:
            state_file = Path(__file__).resolve().parents[2] / "LOOP_STATE.md"
        self._path = Path(state_file)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if not self._path.exists():
            self._path.write_text(
                "# Nexus Loop State\n"
                "status: IDLE\n"
                "current_target: none\n"
                "cycle_count: 0\n"
                "last_updated:\n"
                "history: []\n"
            )

    def read(self) -> dict[str, Any]:
        content = self._path.read_text()
        data: dict[str, Any] = {"history": []}
        for line in content.split("\n"):
            if ": " in line and not line.startswith("#"):
                key, _, value = line.partition(": ")
                key = key.strip()
                value = value.strip()
                if key == "history":
                    try:
                        data[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        data[key] = []
                elif key == "cycle_count":
                    try:
                        data[key] = int(value)
                    except (ValueError, TypeError):
                        data[key] = 0
                else:
                    data[key] = value
        return data

    def write(self, updates: dict[str, Any]) -> None:
        current = self.read()
        current.update(updates)
        current["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        lines = ["# Nexus Loop State"]
        for key, value in current.items():
            if key == "history" and isinstance(value, list):
                lines.append(f"history: {json.dumps(value)}")
            else:
                lines.append(f"{key}: {value}")
        self._path.write_text("\n".join(lines) + "\n")

    def set_target(self, target: str) -> None:
        self.write({"status": "RUNNING", "current_target": target})

    def mark_completed(self) -> None:
        current = self.read()
        history = current.get("history", [])
        if isinstance(history, list):
            history.append({
                "target": current.get("current_target", "unknown"),
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "cycle": current.get("cycle_count", 0),
            })
        self.write({
            "status": "COMPLETED",
            "current_target": "none",
            "history": history,
        })

    def mark_failed(self, reason: str) -> None:
        current = self.read()
        history = current.get("history", [])
        if isinstance(history, list):
            history.append({
                "target": current.get("current_target", "unknown"),
                "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "reason": reason[:500],
                "cycle": current.get("cycle_count", 0),
            })
        self.write({
            "status": "FAILED",
            "current_target": "none",
            "history": history,
        })

    def mark_all_complete(self) -> None:
        self.write({"status": "COMPLETED_ALL"})

    @property
    def status(self) -> str:
        return str(self.read().get("status", "IDLE"))

    @property
    def current_target(self) -> str:
        return str(self.read().get("current_target", "none"))

    @property
    def cycle_count(self) -> int:
        return int(self.read().get("cycle_count", 0))


# Module-level singleton
_loop_state: LoopState | None = None


def get_loop_state() -> LoopState:
    global _loop_state
    if _loop_state is None:
        _loop_state = LoopState()
    return _loop_state
