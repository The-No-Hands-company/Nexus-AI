from __future__ import annotations

from collections import Counter
from typing import Any


RISK_THRESHOLD = 0.6
_ENSEMBLE_ENABLED = True


def get_ensemble_enabled() -> bool:
    return _ENSEMBLE_ENABLED


def set_ensemble_enabled(enabled: bool) -> None:
    global _ENSEMBLE_ENABLED
    _ENSEMBLE_ENABLED = bool(enabled)


def score_task_risk(task: str) -> float:
    lower = (task or "").lower()
    score = 0.0
    weighted_terms = {
        "delete": 0.35,
        "purge": 0.35,
        "drop": 0.35,
        "rm -rf": 0.5,
        "production": 0.25,
        "deploy": 0.25,
        "migration": 0.2,
        "database": 0.2,
    }
    for term, weight in weighted_terms.items():
        if term in lower:
            score += weight
    return min(score, 1.0)


def is_high_risk(task: str, threshold: float = RISK_THRESHOLD) -> bool:
    return score_task_risk(task) >= threshold


def _action_rank(action: dict[str, Any]) -> int:
    kind = str(action.get("action", "respond"))
    ranks = {
        "respond": 0,
        "think": 1,
        "read_file": 2,
        "list_files": 2,
        "web_search": 3,
        "run_command": 6,
        "write_file": 7,
        "delete_file": 8,
    }
    return ranks.get(kind, 4)


def pick_consensus(responses: list[tuple[dict[str, Any], str]]) -> tuple[dict[str, Any], str, bool]:
    if not responses:
        return ({"action": "respond", "content": ""}, "", True)
    if len(responses) == 1:
        return responses[0][0], responses[0][1], True
    kinds = [str(item[0].get("action", "respond")) for item in responses]
    counts = Counter(kinds)
    top_kind, top_count = counts.most_common(1)[0]
    unanimous = top_count == len(responses)
    if top_count >= 2:
        for response, provider_id in responses:
            if response.get("action") == top_kind:
                return response, provider_id, unanimous
    safest = min(responses, key=lambda item: _action_rank(item[0]))
    return safest[0], safest[1], False


def call_llm_ensemble(
    messages: list[dict[str, Any]],
    task: str = "",
    providers_fn=None,
    call_single_fn=None,
    is_rate_limited_fn=None,
    mark_rate_limited_fn=None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    providers_fn = providers_fn or (lambda _task: [])
    call_single_fn = call_single_fn or (lambda _pid, _msgs: {"action": "respond", "content": ""})
    is_rate_limited_fn = is_rate_limited_fn or (lambda _pid: False)
    mark_rate_limited_fn = mark_rate_limited_fn or (lambda _pid: None)
    provider_ids = [pid for pid in providers_fn(task) if not is_rate_limited_fn(pid)]
    meta = {"ensemble": len(provider_ids) >= 2, "unanimous": False, "succeeded": [], "errors": {}, "providers": provider_ids}
    responses: list[tuple[dict[str, Any], str]] = []
    if not provider_ids:
        return {"action": "respond", "content": ""}, "", meta
    for pid in provider_ids:
        try:
            response = call_single_fn(pid, messages)
            responses.append((response, pid))
            meta["succeeded"].append(pid)
        except Exception as exc:
            err_text = str(exc)
            meta["errors"][pid] = err_text
            if "429" in err_text or "rate limit" in err_text.lower():
                mark_rate_limited_fn(pid)
    if not meta["ensemble"] or len(responses) <= 1:
        if responses:
            return responses[0][0], responses[0][1], meta
        return {"action": "respond", "content": ""}, "", meta
    chosen, provider_id, unanimous = pick_consensus(responses)
    meta["unanimous"] = unanimous
    return chosen, provider_id, meta


def call_llm_consensus(
    messages: list[dict[str, Any]],
    task: str = "",
    providers_fn=None,
    call_single_fn=None,
    is_rate_limited_fn=None,
    mark_rate_limited_fn=None,
) -> tuple[str, str, dict[str, Any]]:
    chosen, provider_id, meta = call_llm_ensemble(
        messages=messages,
        task=task,
        providers_fn=providers_fn,
        call_single_fn=call_single_fn,
        is_rate_limited_fn=is_rate_limited_fn,
        mark_rate_limited_fn=mark_rate_limited_fn,
    )
    texts = [str(messages_item[0].get("content", "")) for messages_item in []]
    meta = dict(meta)
    meta["texts"] = texts
    return str(chosen.get("content", "")), provider_id, meta


def explain_consensus(
    responses: list[tuple[dict[str, Any], str]] | None = None,
    *,
    chosen: dict[str, Any] | None = None,
    winning_pid: str | None = None,
    unanimous: bool | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    if responses is not None:
        selected, provider_id, uni = pick_consensus(responses)
        return (
            f"Consensus selected action '{selected.get('action', 'respond')}' from {provider_id}. "
            f"Unanimous={uni}. Providers evaluated={len(responses)}."
        )
    selected = chosen or {"action": "respond"}
    provider_id = winning_pid or "unknown"
    uni = bool(unanimous)
    polled = (meta or {}).get("polled") or (meta or {}).get("providers") or []
    return (
        f"Consensus selected action '{selected.get('action', 'respond')}' from {provider_id}. "
        f"Unanimous={uni}. Providers evaluated={len(polled)}."
    )