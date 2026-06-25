from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")


@dataclass
class CopyrightEntry:
    text: str
    source: str = ""
    metadata: Optional[dict] = None


class CopyrightRegistry:
    def __init__(self) -> None:
        self._entries: list[CopyrightEntry] = []

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"\b\w+\b", text.lower()))

    def register(self, text: str, source: str = "", metadata: Optional[dict] = None) -> None:
        sentences = _SENTENCE_SPLIT.split(text.strip())
        for sentence in sentences:
            s = sentence.strip()
            if s:
                self._entries.append(CopyrightEntry(text=s, source=source, metadata=metadata))

    def check(self, text: str, threshold: float = 0.8) -> list[dict[str, Any]]:
        tokens = self._tokenize(text)
        results: list[dict[str, Any]] = []
        for entry in self._entries:
            entry_tokens = self._tokenize(entry.text)
            intersection = tokens & entry_tokens
            union = tokens | entry_tokens
            if not union:
                continue
            score = len(intersection) / len(union)
            if score >= threshold:
                results.append({
                    "score": score,
                    "matched_text": entry.text,
                    "source": entry.source,
                    "metadata": entry.metadata,
                })
        return results

    def list_entries(self) -> list[CopyrightEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()


_registry: Optional[CopyrightRegistry] = None


def load_registry_from_db() -> CopyrightRegistry:
    global _registry
    if _registry is None:
        _registry = CopyrightRegistry()
    return _registry
