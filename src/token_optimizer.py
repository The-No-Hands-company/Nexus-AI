"""Token usage optimization with response quality safeguards.

Ensures no response feels bad, cut off, or incomplete while minimizing token waste.
Handles vague prompts by adding intelligent disambiguation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Response quality detection ────────────────────────────────────────────────

_TRUNCATION_PATTERNS = [
    re.compile(r"(?:\.{2,3}|…)\s*$"),  # trailing ellipsis
    re.compile(r"[^\s]{3,}$"),          # non-whitespace at end (likely truncated)
    re.compile(r"```\s*$"),            # unclosed code block
    re.compile(r"^\s*$"),               # empty response
]

_MIN_RESPONSE_CHARS = 5
_MAX_RESPONSE_CHARS = 8000  # Safety cap on response length


def is_response_truncated(content: str) -> bool:
    """Check if a response appears truncated or incomplete.

    Returns True if the response looks cut off (ends mid-sentence, unclosed code block, etc.).
    """
    if not content or not content.strip():
        return True

    stripped = content.strip()

    # Too short to be meaningful
    if len(stripped) < _MIN_RESPONSE_CHARS:
        return True

    # Check for trailing ellipsis or unfinished sentence patterns
    if re.search(r"(?:\.{2,3}|…)\s*$", stripped):
        return True

    # Check for unclosed code blocks
    backtick_count = stripped.count("```")
    if backtick_count % 2 != 0:
        return True

    # Check for dangling sentences (ends with comma, conjunction without continuation)
    if re.search(r"(?:,\s*|and\s*|or\s*|but\s*|because\s*|\bthe\b\s*)$", stripped, re.IGNORECASE):
        return True

    return False


def estimate_response_quality(content: str) -> float:
    """Estimate response quality on a 0.0-1.0 scale.

    Factors: length adequacy, structure (headings/lists), sentence count,
    absence of truncation markers.
    """
    if not content or not content.strip():
        return 0.0

    score = 0.5  # Neutral start

    # Length factor
    stripped = content.strip()
    if len(stripped) >= 50:
        score += 0.1
    if len(stripped) >= 200:
        score += 0.05

    # Structure factor (has headings, lists, or code blocks)
    if re.search(r"^#{1,3}\s", stripped, re.MULTILINE):
        score += 0.1
    if re.search(r"^[-*+]\s", stripped, re.MULTILINE):
        score += 0.05

    # Sentence count factor
    sentences = re.split(r"[.!?]+", stripped)
    if len(sentences) >= 2:
        score += 0.05

    # Truncation penalty
    if is_response_truncated(content):
        score -= 0.5

    return max(0.0, min(1.0, score))


# ── Vague prompt detection and disambiguation ─────────────────────────────────

_VAGUE_PATTERNS = [
    (re.compile(r"^\s*(?:hi|hey|hello|yo|sup|helo)\s*$", re.IGNORECASE), "greeting"),
    (re.compile(r"^\s*(?:what\?|huh\?|wut\?|what)\s*$", re.IGNORECASE), "confused"),
    (re.compile(r"^\s*(?:help|help me|halp|plz help|please help)\s*$", re.IGNORECASE), "help_request"),
    (re.compile(r"^\s*(?:idk|i don.?t know|not sure)\s*$", re.IGNORECASE), "uncertain"),
    (re.compile(r"^\s*(?:ok|okay|k|kk|alright|fine|sure)\s*$", re.IGNORECASE), "acknowledgment"),
    (re.compile(r"^\s*(?:no|nope|nah|n)\s*$", re.IGNORECASE), "negation"),
    (re.compile(r"^\s*(?:yes|yea|yeah|yep|y|ya|yup|sure|absolutely)\s*$", re.IGNORECASE), "affirmation"),
    (re.compile(r"^\s*(?:continue|go on|proceed|next|and then)\s*$", re.IGNORECASE), "continue"),
]

_MIN_VAGUE_LENGTH = 20  # Prompts shorter than this are considered potentially vague


def is_vague_prompt(task: str) -> Optional[str]:
    """Detect if a user prompt is vague and return the vague category.

    Returns None if the prompt is specific enough, or a category string indicating
    the type of vagueness (greeting, help_request, etc.).
    """
    stripped = (task or "").strip()

    # Short prompts are likely vague
    if len(stripped) < _MIN_VAGUE_LENGTH:
        for pattern, category in _VAGUE_PATTERNS:
            if pattern.match(stripped):
                return category

        # Short but not matching any known pattern — still potentially vague
        if len(stripped) < 10:
            return "short_prompt"

    # Longer prompts that are still vague (open-ended questions without context)
    vague_indicators = [
        re.compile(r"^\s*what\s+(?:do|should|can|could|would)\s+(?:i|you|we)\s+(?:do|make|build|create|use)\b", re.IGNORECASE),
        re.compile(r"^\s*how\s+(?:do|should|can|could|would)\s+(?:i|you|we)\b", re.IGNORECASE),
        re.compile(r"^\s*tell\s+me\s+(?:about|something|anything|more)\s*$", re.IGNORECASE),
        re.compile(r"^\s*what.?s?\s*(?:new|up|happening|going on)\s*$", re.IGNORECASE),
        re.compile(r"^\s*explain\s+(?:this|that|it)\s*$", re.IGNORECASE),
    ]
    for pattern in vague_indicators:
        if pattern.match(stripped):
            return "open_ended"

    return None


def get_vague_prompt_clarification(category: str, task: str) -> Optional[str]:
    """Generate a clarification question for a vague prompt.

    Returns a clarifying question to ask the user, or None if no clarification needed.
    """
    clarifications = {
        "greeting": "Hello! What would you like help with today? I can assist with coding, research, task automation, or just answering questions.",
        "help_request": "I'm happy to help! Could you tell me a bit more about what you need? For example, what specific task or problem are you working on?",
        "short_prompt": "That's a short prompt — could you share a few more details about what you're looking for? The more context you give me, the better I can help.",
        "open_ended": "That's an interesting question! To give you the most helpful answer, could you narrow it down a bit? For example, are you asking about a specific technology, project, or use case?",
        "confused": "I want to make sure I understand correctly. Could you rephrase or share more context about what you're asking?",
        "uncertain": "It sounds like you might be unsure about something. Could you tell me more about the situation? I can help explore options or find answers.",
        "continue": "Just to confirm — would you like me to continue from where I left off, or is there something new you'd like to work on?",
    }
    return clarifications.get(category)


# ── Token budget estimation ───────────────────────────────────────────────────

def estimate_task_tokens(task: str) -> int:
    """Estimate token count for a task string using a simple heuristic.

    Uses ~3.5 chars per token approximation (GPT-4 average for English).
    """
    return max(1, len(task) * 2 // 7)


def recommend_response_tokens(task_tokens: int, complexity: str = "standard") -> int:
    """Recommend a target response token count based on task complexity.

    Returns a suggested max_tokens value for the LLM call.
    """
    base = task_tokens * 2  # Response should be at most ~2x the task length

    if complexity == "minimal":
        return min(base, 512)
    elif complexity == "detailed":
        return min(max(base, 1024), 4096)
    else:  # standard
        return min(max(base, 256), 2048)


# ── Response optimization ─────────────────────────────────────────────────────

def optimize_response(content: str, max_chars: int = 4000) -> str:
    """Optimize a response for token efficiency while preserving quality.

    - Trims excessive whitespace
    - Caps response length at max_chars
    - Ensures it doesn't end mid-sentence if truncated
    - Returns the original if it's already within limits and of good quality
    """
    if not content or not content.strip():
        return "I received an empty response. Could you please rephrase your question?"

    stripped = content.strip()

    # Already within limits and good quality
    if len(stripped) <= max_chars and not is_response_truncated(stripped):
        return stripped

    # Need to truncate — try to end at a sentence boundary
    if len(stripped) > max_chars:
        truncated = stripped[:max_chars]
        # Find last sentence end within truncated text
        last_period = max(
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
            truncated.rfind("\n\n"),
        )
        if last_period > max_chars // 2:
            return truncated[: last_period + 1] + "\n\n*(Response truncated to stay within length limits.)*"
        else:
            return truncated + "…\n\n*(Response truncated.)*"

    return stripped
