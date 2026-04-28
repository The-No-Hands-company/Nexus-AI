from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SafetyAction(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REDACT = "redact"
    REVIEW = "review"


@dataclass
class SafetyIssue:
    code: str
    message: str
    severity: str = "medium"
    pattern: str | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "reason": self.message,
            "detail": self.message,
            "message": self.message,
            "severity": self.severity,
            "threat": self.severity,
            "pattern": self.pattern,
        }


@dataclass
class SafetyDecision:
    allowed: bool
    action: SafetyAction
    stage: str
    issues: list[SafetyIssue] = field(default_factory=list)
    masked_text: str | None = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "action": self.action.value,
            "stage": self.stage,
            "issues": [issue.to_dict() for issue in self.issues],
            "masked_text": self.masked_text,
        }