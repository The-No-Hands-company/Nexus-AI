from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextWindowConfig:
    max_turns: int = 20
    min_head_turns: int = 2
    min_tail_turns: int = 4
    summary_label: str = "[EARLIER CONVERSATION SUMMARY]"


class ContextWindowManager:
    def __init__(self, config: ContextWindowConfig | None = None) -> None:
        self.config = config or ContextWindowConfig()

    def _token_count(self, message: dict) -> int:
        return max(1, len(str(message.get("content", ""))) // 4)

    def token_breakdown(self, history: list[dict]) -> list[dict]:
        return [
            {"index": idx, "role": item.get("role", "user"), "tokens": self._token_count(item)}
            for idx, item in enumerate(history)
        ]

    def get_model_context_budget(self, model: str, default_budget: int = 32768) -> int:
        budgets = {"gpt-4o": 128000, "gpt-4o-mini": 128000, "claude": 200000, "llm7": 8192}
        return budgets.get(model, default_budget)

    def compress_history(self, history: list[dict]) -> list[dict]:
        max_messages = self.config.max_turns * 2
        if len(history) <= max_messages:
            return list(history)
        head = history[: self.config.min_head_turns * 2]
        tail = history[-self.config.min_tail_turns * 2 :]
        middle = history[len(head) : len(history) - len(tail)]
        summary_text = "; ".join(str(item.get("content", ""))[:80] for item in middle[:8])
        summary = {"role": "system", "content": f"{self.config.summary_label}\n{summary_text}"}
        return head + [summary] + tail

    def compress_to_token_budget(self, history: list[dict], token_budget: int, reserve_tokens: int = 0) -> list[dict]:
        allowed = max(1, token_budget - reserve_tokens)
        running = 0
        kept: list[dict] = []
        for item in reversed(history):
            tokens = self._token_count(item)
            if kept and running + tokens > allowed:
                break
            kept.append(item)
            running += tokens
        return list(reversed(kept))

    def compress_history_with_llm(self, history: list[dict], summarizer) -> list[dict]:
        max_messages = self.config.max_turns * 2
        if len(history) <= max_messages:
            return list(history)
        head = history[: self.config.min_head_turns * 2]
        tail = history[-self.config.min_tail_turns * 2 :]
        middle = history[len(head) : len(history) - len(tail)]
        prompt = "Summarize the earlier conversation for future continuation:\n\n" + "\n".join(
            f"{item.get('role')}: {item.get('content')}" for item in middle
        )
        summary_text = summarizer(prompt)
        return head + [{"role": "system", "content": f"{self.config.summary_label}\n{summary_text}"}] + tail