from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class CodeSample:
    prompt: str
    target: str
    language: str
    language_edition: str
    license: str
    source_type: str
    source_uri: str
    difficulty: str = "unknown"

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["messages"] = [
            {"role": "user", "content": self.prompt.strip()},
            {"role": "assistant", "content": self.target.strip()},
        ]
        return row


def normalize_code_row(obj: dict[str, Any]) -> CodeSample | None:
    prompt = str(obj.get("prompt") or obj.get("instruction") or "").strip()
    target = str(obj.get("target") or obj.get("response") or obj.get("output") or "").strip()
    language = str(obj.get("language") or "unknown").strip().lower()
    edition = str(obj.get("language_edition") or obj.get("edition") or "generic").strip()
    license_name = str(obj.get("license") or "UNKNOWN").strip()
    source_type = str(obj.get("source_type") or "repo").strip().lower()
    source_uri = str(obj.get("source_uri") or obj.get("source") or "").strip()
    difficulty = str(obj.get("difficulty") or "unknown").strip().lower()

    if not prompt or not target:
        return None

    return CodeSample(
        prompt=prompt,
        target=target,
        language=language,
        language_edition=edition,
        license=license_name,
        source_type=source_type,
        source_uri=source_uri,
        difficulty=difficulty,
    )
