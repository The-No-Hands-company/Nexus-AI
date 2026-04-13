from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ContentCategory(str, Enum):
    SAFE = "safe"
    PII = "pii"
    SECRET = "secret"
    PROMPT_INJECTION = "prompt_injection"
    DESTRUCTIVE = "destructive"
    HIGH_STAKES = "high_stakes"
    TOOL = "tool"


class ThreatLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SafetyAction(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    REDACT = "redact"
    BLOCK = "block"


@dataclass
class PIIMatch:
    pii_type: str
    match: str
    start: int
    end: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.pii_type,
            "match": self.match,
            "start": self.start,
            "end": self.end,
        }


@dataclass
class SafetySignal:
    code: str
    reason: str
    category: ContentCategory
    threat: ThreatLevel
    action: SafetyAction
    detail: Optional[str] = None
    pattern: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "reason": self.reason,
            "category": self.category.value,
            "threat": self.threat.value,
            "action": self.action.value,
            "detail": self.detail,
            "pattern": self.pattern,
        }


@dataclass
class SafetyVerdict:
    stage: str
    allowed: bool
    action: SafetyAction = SafetyAction.ALLOW
    threat: ThreatLevel = ThreatLevel.NONE
    issues: List[SafetySignal] = field(default_factory=list)
    masked_text: Optional[str] = None
    pii_matches: List[PIIMatch] = field(default_factory=list)

    def primary_issue(self) -> Optional[SafetySignal]:
        return self.issues[0] if self.issues else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "allowed": self.allowed,
            "action": self.action.value,
            "threat": self.threat.value,
            "issues": [issue.to_dict() for issue in self.issues],
            "masked_text": self.masked_text,
            "pii_matches": [match.to_dict() for match in self.pii_matches],
        }