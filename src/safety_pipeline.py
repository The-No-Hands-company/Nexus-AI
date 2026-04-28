from __future__ import annotations

from .safety import check_text_against_guardrail, scrub_pii, _scrub_text_str
from .safety_types import SafetyAction, SafetyDecision, SafetyIssue


SAFETY_POLICY_PROFILES = {
    "standard": {
        "allow_destructive": False,
        "allow_destructive_input": False,
        "allow_destructive_output": False,
    },
    "strict": {
        "allow_destructive": False,
        "allow_destructive_input": False,
        "allow_destructive_output": False,
    },
    "research": {
        "allow_destructive": False,
        "allow_destructive_input": False,
        "allow_destructive_output": False,
    },
    "sandbox": {
        "allow_destructive": True,
        "allow_destructive_input": True,
        "allow_destructive_output": True,
    },
}


def get_safety_policy(profile: str = "standard") -> dict:
    return dict(SAFETY_POLICY_PROFILES.get(profile or "standard", SAFETY_POLICY_PROFILES["standard"]))


def describe_block(code: str) -> str:
    mapping = {
        "prompt_injection": "Prompt injection attempt detected.",
        "destructive_command": "Destructive command detected.",
        "tool_destructive_command": "Tool action was destructive.",
        "tool_high_stakes_denylist": "Tool action requested a disallowed high-stakes task.",
    }
    return mapping.get(code, code.replace("_", " "))


def explain_prompt_injection(text: str) -> dict:
    lower = (text or "").lower()
    matches = [term for term in ("ignore previous instructions", "developer mode", "system prompt", "reveal hidden policies") if term in lower]
    return {
        "matched_patterns": matches,
        "safer_rewrite": "Ask for the information directly without trying to override system instructions.",
    }


def screen_input(text: str, allow_destructive: bool = False, policy_profile: str = "standard") -> SafetyDecision:
    policy = get_safety_policy(policy_profile)
    decision = check_text_against_guardrail(text, allow_destructive=allow_destructive or policy.get("allow_destructive", False), policy_profile=policy_profile)
    lower = (text or "").lower()
    if any(term in lower for term in ("prescribe medication", "medical dosage", "dosage for this patient")):
        issues = list(decision.issues) + [SafetyIssue(code="high_stakes_denylist", message="Medical dosage advice is blocked", severity="high")]
        return SafetyDecision(False, SafetyAction.BLOCK, "input", issues=issues, masked_text=decision.masked_text)
    return SafetyDecision(decision.allowed, decision.action, "input", issues=decision.issues, masked_text=decision.masked_text)


def screen_output(text: str, policy_profile: str = "standard") -> SafetyDecision:
    masked = _scrub_text_str(text or "")
    if masked != (text or ""):
        return SafetyDecision(True, SafetyAction.REDACT, "output", issues=[SafetyIssue(code="secret_token", message="Sensitive token redacted", severity="high")], masked_text=masked)
    return SafetyDecision(True, SafetyAction.ALLOW, "output", issues=[], masked_text=None)


def screen_tool_action(action_payload: dict, policy_profile: str = "standard") -> SafetyDecision:
    payload = dict(action_payload)
    profile = str(payload.get("policy_profile") or policy_profile or "standard")
    lower = f"{payload.get('action', '')} {payload.get('cmd', '')} {payload.get('path', '')}".lower()
    issues: list[SafetyIssue] = []
    if any(term in lower for term in ("ransomware", "malware", "deploy ransomware")):
        issues.append(SafetyIssue(code="tool_high_stakes_denylist", message="High-stakes harmful tool action", severity="critical"))
    destructive = any(term in lower for term in ("rm -rf", "delete_file", "write_file")) and payload.get("action") == "run_command" or "rm -rf" in lower
    if destructive and profile != "sandbox":
        issues.append(SafetyIssue(code="tool_destructive_command", message="Destructive tool action", severity="high"))
    if issues:
        return SafetyDecision(False, SafetyAction.BLOCK, "tool", issues=issues, masked_text=None)
    return SafetyDecision(True, SafetyAction.ALLOW, "tool", issues=[], masked_text=None)