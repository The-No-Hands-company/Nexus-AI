from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


_MODEL_CONTEXT_BUDGETS: Dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4.1": 128000,
    "gpt-5": 200000,
    "claude-3": 200000,
    "claude-4": 200000,
    "gemini": 1000000,
    "llama": 128000,
    "qwen": 128000,
    "deepseek": 128000,
    "mistral": 128000,
    "mixtral": 32768,
}


def _is_user_turn(message: Dict) -> bool:
    return message.get("role") in ("user", "assistant")


def _is_system_or_tool_message(message: Dict) -> bool:
    content = message.get("content", "")
    if not isinstance(content, str):
        return False
    return content.startswith("Tool result:") or content.startswith("Continue") or content.startswith("[MEMORY")


@dataclass
class ContextWindowConfig:
    max_turns: int = 20
    min_head_turns: int = 2
    min_tail_turns: int = 14
    summary_prefix: str = "[EARLIER CONVERSATION SUMMARY]"
    summary_separator: str = "\n"


class ContextWindowManager:
    def __init__(self, config: Optional[ContextWindowConfig] = None):
        self.config = config or ContextWindowConfig()

    def compress_history(self, history: List[Dict]) -> List[Dict]:
        if len(history) <= self.config.max_turns:
            return history

        real_turns = [
            (idx, msg)
            for idx, msg in enumerate(history)
            if _is_user_turn(msg) and not _is_system_or_tool_message(msg)
        ]

        if len(real_turns) <= self.config.max_turns:
            return history

        head_count = self.config.min_head_turns
        tail_count = self.config.min_tail_turns
        head_idx = real_turns[head_count][0] if len(real_turns) > head_count else 0
        tail_idx = real_turns[-tail_count][0] if len(real_turns) > tail_count else real_turns[-1][0]

        if tail_idx <= head_idx:
            return history[-self.config.max_turns:]

        old_turns = history[:head_idx]
        new_turns = history[tail_idx:]

        summary_lines = []
        for msg in old_turns:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if _is_system_or_tool_message(msg):
                continue
            label = "User" if role == "user" else "Assistant"
            summary_lines.append(f"{label}: {content.strip()[:200]}")

        summary_text = self.config.summary_prefix
        if summary_lines:
            summary_text += self.config.summary_separator + self.config.summary_separator.join(summary_lines[-30:])

        compressed = [
            {"role": "user", "content": summary_text},
            {"role": "assistant", "content": "Understood — I have context from the earlier conversation."},
        ]
        return compressed + new_turns

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def token_breakdown(self, history: List[Dict]) -> List[Dict]:
        breakdown: List[Dict] = []
        for idx, msg in enumerate(history):
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts: List[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(str(part.get("text", "")))
                text = "\n".join(text_parts)
            else:
                text = content if isinstance(content, str) else str(content)
            breakdown.append(
                {
                    "index": idx,
                    "role": msg.get("role", ""),
                    "tokens": self.estimate_tokens(text),
                    "preview": text[:120],
                }
            )
        return breakdown

    def get_model_context_budget(self, model_name: str, default_budget: int = 32768) -> int:
        low = (model_name or "").lower()
        if not low:
            return default_budget
        for prefix, budget in _MODEL_CONTEXT_BUDGETS.items():
            if prefix in low:
                return budget
        return default_budget

    def compress_to_token_budget(
        self,
        history: List[Dict],
        token_budget: int,
        reserve_tokens: int = 4096,
    ) -> List[Dict]:
        target_budget = max(2048, int(token_budget) - int(reserve_tokens))
        if target_budget <= 0:
            return history[-self.config.max_turns :]

        compressed = self.compress_history(history)
        if sum(item["tokens"] for item in self.token_breakdown(compressed)) <= target_budget:
            return compressed

        # Deterministic fallback: keep latest messages that fit budget.
        out: List[Dict] = []
        running = 0
        for msg in reversed(compressed):
            content = msg.get("content", "")
            if isinstance(content, list):
                joined = "\n".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                joined = content if isinstance(content, str) else str(content)
            cost = self.estimate_tokens(joined)
            if running + cost > target_budget:
                continue
            out.append(msg)
            running += cost
        return list(reversed(out)) if out else compressed[-self.config.max_turns :]

    def compress_history_with_llm(
        self,
        history: List[Dict],
        summarize_fn: Callable[[str], str],
    ) -> List[Dict]:
        """Like compress_history but uses ``summarize_fn`` to produce an abstractive
        LLM-generated summary of the pruned turns instead of a naive truncation.

        ``summarize_fn(text: str) -> str`` should call an LLM and return a
        short narrative summary of the conversation excerpt.
        """
        if len(history) <= self.config.max_turns:
            return history

        real_turns = [
            (idx, msg)
            for idx, msg in enumerate(history)
            if _is_user_turn(msg) and not _is_system_or_tool_message(msg)
        ]

        if len(real_turns) <= self.config.max_turns:
            return history

        head_count = self.config.min_head_turns
        tail_count = self.config.min_tail_turns
        head_idx = real_turns[head_count][0] if len(real_turns) > head_count else 0
        tail_idx = real_turns[-tail_count][0] if len(real_turns) > tail_count else real_turns[-1][0]

        if tail_idx <= head_idx:
            return history[-self.config.max_turns:]

        old_turns = history[:head_idx]
        new_turns = history[tail_idx:]

        # Build a plain-text transcript for the summarizer
        lines = []
        for msg in old_turns:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if _is_system_or_tool_message(msg):
                continue
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {content.strip()[:400]}")

        transcript = "\n".join(lines[-40:])
        prompt = (
            "Summarise the following conversation excerpt in 3-5 concise sentences, "
            "preserving key decisions, facts, and user goals:\n\n" + transcript
        )
        try:
            summary_text = summarize_fn(prompt)
        except Exception:
            # Fall back to naive truncation summary on LLM failure
            summary_text = self.config.summary_prefix
            if lines:
                summary_text += self.config.summary_separator + self.config.summary_separator.join(
                    line[:200] for line in lines[-30:]
                )

        compressed = [
            {"role": "user", "content": self.config.summary_prefix + "\n" + summary_text},
            {"role": "assistant", "content": "Understood — I have context from the earlier conversation."},
        ]
        return compressed + new_turns
