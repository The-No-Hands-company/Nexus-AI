"""
Nexus AI — High-risk ensemble/consensus routing.

When a task is classified as high-risk (score >= RISK_THRESHOLD) we poll up
to ENSEMBLE_SIZE providers *in parallel* and reconcile their responses using a
majority-vote / risk-level tiebreak consensus algorithm before returning a
single result to the caller.

Risk is scored independently of complexity:
  - Destructive language (delete, rm, purge, wipe, drop …)
  - Mutation/deployment language (push, deploy, overwrite, install …)
  - SQL mutations (UPDATE … SET, INSERT INTO, DROP TABLE …)

If fewer than MIN_ENSEMBLE_SIZE providers respond successfully we fall back
to the standard call_llm_with_fallback() path automatically.
"""

from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── tunables ──────────────────────────────────────────────────────────────────
ENSEMBLE_SIZE     = 3    # max providers to poll in parallel
MIN_ENSEMBLE_SIZE = 2    # minimum successes needed before trusting consensus
RISK_THRESHOLD    = 0.4  # tasks at or above this score enter ensemble mode

# ── risk vocabulary ───────────────────────────────────────────────────────────
_RISK_RE = re.compile(
    r'\b('
    r'delete|remove|drop|truncate|format|overwrite|push|deploy|execute|'
    r'run\b|install|uninstall|rm\b|kill|stop|restart|shutdown|purge|wipe|'
    r'erase|destroy|migrate|alter\s+table|drop\s+table|update.*?set\b|'
    r'insert\s+into|commit|force[-\s]?push'
    r')\b',
    re.IGNORECASE,
)

# Action names ordered from safest (index 0) to most risky (highest index).
# Actions absent from this list are treated as medium-risk.
_ACTION_RISK_ORDER: List[str] = [
    "respond", "think", "think_deep", "clarify", "plan",
    "get_time", "calculate", "weather", "currency", "convert",
    "regex", "base64", "json_format",
    "read_file", "list_files", "read_page", "read_pdf",
    "youtube_transcript", "youtube", "web_search",
    "query_db",                   # assumed read-only
    "image_gen", "generate_image",
    "write_file", "clone_repo", "create_repo", "api_call",
    "sub_agent", "orchestrate_goal", "decompose_goal",
    "run_command", "commit_push", "delete_file",
]


# ── public API ─────────────────────────────────────────────────────────────────

def score_task_risk(task: str) -> float:
    """Return a risk score in [0.0, 1.0]. >= RISK_THRESHOLD triggers ensemble mode."""
    hits = len(_RISK_RE.findall(task))
    score = min(0.6, hits * 0.2)      # each risky keyword adds 0.2, capped at 0.6
    if len(task) > 400:
        score += 0.1                  # long tasks are more likely to have side-effects
    return min(1.0, score)


def is_high_risk(task: str) -> bool:
    """Convenience predicate — True when ensemble mode should be engaged."""
    return score_task_risk(task) >= RISK_THRESHOLD


def action_risk_level(action: str) -> int:
    """Lower index = safer action. Unknown actions get middle rank."""
    try:
        return _ACTION_RISK_ORDER.index(action)
    except ValueError:
        return len(_ACTION_RISK_ORDER) // 2


def _safe_action(response: Any) -> str:
    if isinstance(response, dict):
        return response.get("action", "respond")
    return "respond"


def pick_consensus(
    responses: List[Tuple[Dict[str, Any], str]],
) -> Tuple[Dict[str, Any], str, bool]:
    """
    Given [(response_dict, provider_id), ...] select the best result.

    Returns:
        (chosen_response, provider_id, is_unanimous)

    Strategy:
    1. Majority vote on ``action`` type.
    2. Ties break toward the *safer* (lower-risk) action — prefer
       not mutating state when providers disagree.
    """
    if not responses:
        raise ValueError("pick_consensus: empty response list")

    if len(responses) == 1:
        r, pid = responses[0]
        return r, pid, True

    action_counts = Counter(_safe_action(r) for r, _ in responses)
    majority_action, top_count = action_counts.most_common(1)[0]
    is_unanimous = top_count == len(responses)
    has_majority = top_count > len(responses) // 2

    if has_majority:
        # Return the first response whose action matches the majority type.
        for r, pid in responses:
            if _safe_action(r) == majority_action:
                return r, pid, is_unanimous

    # No clear majority — resolve by picking the safest action.
    safest = min(responses, key=lambda x: action_risk_level(_safe_action(x[0])))
    return safest[0], safest[1], False


def call_llm_ensemble(
    messages: List[Dict],
    task: str,
    providers_fn: Callable[[str], List[str]],
    call_single_fn: Callable[[str, List[Dict]], Dict],
    is_rate_limited_fn: Callable[[str], bool],
    mark_rate_limited_fn: Callable[[str], None],
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    """
    Poll up to ENSEMBLE_SIZE providers in parallel and reconcile their
    responses via consensus.

    Returns:
        (result_dict, winning_provider_id, metadata_dict)

    Metadata keys:
        ensemble      — bool, whether ensemble mode ran successfully
        polled        — list[str] provider IDs that were called
        succeeded     — list[str] provider IDs that returned a valid result
        unanimous     — bool
        action_votes  — dict mapping action-type → count
        risk_score    — float
        errors        — dict mapping provider ID → error string
    """
    risk = score_task_risk(task)
    meta: Dict[str, Any] = {
        "ensemble":    True,
        "risk_score":  risk,
        "errors":      {},
    }

    order         = providers_fn(task)
    ensemble_pids = [pid for pid in order if not is_rate_limited_fn(pid)][:ENSEMBLE_SIZE]
    meta["polled"] = list(ensemble_pids)

    results: List[Tuple[Dict, str]] = []

    def _call(pid: str) -> Tuple[str, Dict]:
        return pid, call_single_fn(pid, messages)

    with ThreadPoolExecutor(max_workers=ENSEMBLE_SIZE) as pool:
        futures = {pool.submit(_call, pid): pid for pid in ensemble_pids}
        for future in as_completed(futures, timeout=120):
            pid = futures[future]
            try:
                _, result = future.result()
                results.append((result, pid))
            except Exception as exc:
                meta["errors"][pid] = str(exc)
                if "rate limit" in str(exc).lower() or "429" in str(exc):
                    mark_rate_limited_fn(pid)

    meta["succeeded"] = [pid for _, pid in results]

    if len(results) < MIN_ENSEMBLE_SIZE:
        # Not enough data for a reliable consensus — signal caller to fall back.
        meta["ensemble"] = False
        if results:
            best, pid = results[0]
            meta["unanimous"]   = True
            meta["action_votes"] = {_safe_action(best): 1}
            return best, pid, meta
        raise RuntimeError("Ensemble: all providers failed")

    chosen, winning_pid, unanimous = pick_consensus(results)
    meta["unanimous"]    = unanimous
    meta["action_votes"] = dict(Counter(_safe_action(r) for r, _ in results))

    if not unanimous:
        print(
            f"⚖️  Ensemble diverged: {meta['action_votes']} "
            f"→ picked '{_safe_action(chosen)}' from {winning_pid}"
        )
    else:
        print(
            f"✅ Ensemble unanimous: '{_safe_action(chosen)}' "
            f"({len(results)}/{len(ensemble_pids)} providers)"
        )

    return chosen, winning_pid, meta


def call_llm_consensus(
    messages: List[Dict],
    task: str,
    providers_fn: Callable[[str], List[str]],
    call_single_fn: Callable[[str, List[Dict]], Dict],
    is_rate_limited_fn: Callable[[str], bool],
    mark_rate_limited_fn: Callable[[str], None],
) -> Tuple[str, str, Dict[str, Any]]:
    """Run the same task through up to ENSEMBLE_SIZE providers and reconcile
    their *text content* into a single consensus answer.

    Unlike ``call_llm_ensemble`` (which reconciles at the action/JSON level),
    this function is intended for free-text reasoning tasks where the caller
    needs a synthesised narrative rather than a structured action choice.

    Returns:
        (consensus_text, winning_provider_id, metadata_dict)

    Metadata keys (superset of call_llm_ensemble metadata):
        ensemble      — bool
        polled        — list[str]
        succeeded     — list[str]
        texts         — dict mapping provider_id → extracted text
        errors        — dict mapping provider_id → error string
    """
    chosen, winning_pid, meta = call_llm_ensemble(
        messages=messages,
        task=task,
        providers_fn=providers_fn,
        call_single_fn=call_single_fn,
        is_rate_limited_fn=is_rate_limited_fn,
        mark_rate_limited_fn=mark_rate_limited_fn,
    )

    # Extract text-level content from the winning response
    if isinstance(chosen, dict):
        text = chosen.get("content") or chosen.get("thought") or chosen.get("consensus") or str(chosen)
    else:
        text = str(chosen)

    meta["texts"] = {winning_pid: text}
    return text, winning_pid, meta
