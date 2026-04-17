"""
src/safety/pii.py — PII detection and redaction stub

Detects and optionally redacts Personally Identifiable Information
from prompt and response text.

PII categories: email, phone, SSN, credit card, IP address, name,
address, date-of-birth, passport, driving licence.

This module is a STUB — detect/redact raise NotImplementedError.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Quick-pattern detectors (FUNCTIONAL — not stubs)
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?1?\s?)?(\(?\d{3}\)?[\s.\-]?)(\d{3}[\s.\-]\d{4})")
CREDIT_CARD_RE = re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@dataclass
class PIIMatch:
    category: str
    value: str
    start: int
    end: int
    redacted: str = "[REDACTED]"


def detect_pii(text: str) -> list[PIIMatch]:
    """
    Detect PII in *text* using regex patterns.

    Returns a list of PIIMatch objects for each detected PII span.
    FUNCTIONAL for regex-based categories; NER-based detection is a stub.
    """
    matches: list[PIIMatch] = []
    for m in EMAIL_RE.finditer(text):
        matches.append(PIIMatch("email", m.group(), m.start(), m.end()))
    for m in PHONE_RE.finditer(text):
        matches.append(PIIMatch("phone", m.group(), m.start(), m.end()))
    for m in CREDIT_CARD_RE.finditer(text):
        matches.append(PIIMatch("credit_card", m.group(), m.start(), m.end()))
    for m in SSN_RE.finditer(text):
        matches.append(PIIMatch("ssn", m.group(), m.start(), m.end()))
    return matches


def redact_pii(text: str, replacement: str = "[REDACTED]") -> str:
    """
    Redact all detected PII from *text*.

    FUNCTIONAL for regex patterns.
    NER-based redaction (names, addresses) is a stub.
    """
    text = EMAIL_RE.sub(replacement, text)
    text = PHONE_RE.sub(replacement, text)
    text = CREDIT_CARD_RE.sub(replacement, text)
    text = SSN_RE.sub(replacement, text)
    return text


def detect_pii_ner(text: str) -> list[PIIMatch]:
    """Best-effort NER fallback using lightweight regex/name heuristics."""
    matches: list[PIIMatch] = []

    # Naive PERSON detection: sequences of 2-3 capitalized words.
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", text):
        val = m.group(1)
        # Avoid obvious non-person terms.
        if val.lower() in {"new york", "san francisco", "open ai"}:
            continue
        matches.append(PIIMatch("person", val, m.start(), m.end(), "[REDACTED_PERSON]"))

    # Date of birth / date-like sequences.
    for m in re.finditer(r"\b(?:\d{1,2}[/-]){2}\d{2,4}\b", text):
        matches.append(PIIMatch("date", m.group(), m.start(), m.end(), "[REDACTED_DATE]"))

    # Address-like heuristic.
    for m in re.finditer(r"\b\d{1,5}\s+[A-Za-z0-9.\- ]+\s(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr)\b", text):
        matches.append(PIIMatch("address", m.group(), m.start(), m.end(), "[REDACTED_ADDRESS]"))

    return matches
