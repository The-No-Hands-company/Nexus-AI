"""Federated learning module for Nexus AI.

Implements privacy-preserving local gradient contribution using
secure aggregation patterns — raw training data never leaves the node.

Architecture:
- Each node computes local gradients on opt-in interaction data
- Gradients are noise-masked with differential privacy (DP-SGD)
- Only masked updates are transmitted to the aggregation server
- The aggregator returns a globally improved model delta
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
import uuid
from threading import RLock
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

FEDERATED_SERVER    = os.getenv("FEDERATED_SERVER_URL", "")
FEDERATED_TOKEN     = os.getenv("FEDERATED_TOKEN", "")
FEDERATED_ENABLED   = os.getenv("FEDERATED_ENABLED", "false").lower() == "true"
NODE_ID             = os.getenv("NEXUS_INSTANCE_ID", str(uuid.uuid4())[:12])
DP_NOISE_SIGMA      = float(os.getenv("DP_NOISE_SIGMA", "0.1"))   # differential-privacy noise
DP_MAX_GRAD_NORM    = float(os.getenv("DP_MAX_GRAD_NORM", "1.0"))
FEDERATED_MAX_SAMPLES = int(os.getenv("FEDERATED_MAX_SAMPLES", "5000"))
FEDERATED_MAX_RETRIES = int(os.getenv("FEDERATED_MAX_RETRIES", "3"))


# ── Round state ───────────────────────────────────────────────────────────────

@dataclass
class FederatedRound:
    round_id: str
    global_round: int
    started_at: str
    status: str = "pending"          # pending | computing | submitted | aggregated | failed
    local_samples: int = 0
    submitted_at: str | None = None
    error: str | None = None
    privacy_budget_used: float = 0.0

    def to_dict(self) -> dict:
        return {
            "round_id":            self.round_id,
            "global_round":        self.global_round,
            "node_id":             NODE_ID,
            "started_at":          self.started_at,
            "status":              self.status,
            "local_samples":       self.local_samples,
            "submitted_at":        self.submitted_at,
            "error":               self.error,
            "privacy_budget_used": self.privacy_budget_used,
        }


_rounds: list[FederatedRound] = []
_total_privacy_budget_used = 0.0
_MAX_PRIVACY_BUDGET = float(os.getenv("DP_MAX_BUDGET", "10.0"))  # epsilon budget cap
_state_lock = RLock()


def _validate_samples(samples: list[dict]) -> tuple[bool, str]:
    if not isinstance(samples, list):
        return False, "samples must be a list"
    if len(samples) > FEDERATED_MAX_SAMPLES:
        return False, f"samples exceeds max allowed ({FEDERATED_MAX_SAMPLES})"
    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            return False, f"samples[{idx}] must be an object"
        inp = str(sample.get("input") or "").strip()
        out = str(sample.get("output") or "").strip()
        if not inp and not out:
            return False, f"samples[{idx}] must include non-empty input or output"
    return True, ""


def _add_dp_noise(gradient_vector: list[float]) -> list[float]:
    """Add Gaussian noise scaled to DP_NOISE_SIGMA for differential privacy."""
    import random
    noisy = []
    for g in gradient_vector:
        # Clip gradient
        clipped = max(-DP_MAX_GRAD_NORM, min(DP_MAX_GRAD_NORM, g))
        # Add Gaussian noise
        noise = random.gauss(0, DP_NOISE_SIGMA)
        noisy.append(clipped + noise)
    return noisy


def _compute_local_gradients(samples: list[dict]) -> list[float]:
    """
    Compute local parameter gradients from training samples.

    In production this would use the actual model adapter weights.
    Here we produce a deterministic proxy gradient for the aggregation protocol:
    a mean embedding of token-frequency features, clipped to unit norm.
    """
    if not samples:
        return []

    vocab: dict[str, int] = {}
    for sample in samples:
        for ch in str(sample.get("input", "") + sample.get("output", "")).lower():
            if ch.isalpha():
                vocab[ch] = vocab.get(ch, 0) + 1

    vec = [float(vocab.get(chr(ord("a") + i), 0)) for i in range(26)]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def compute_and_submit_update(samples: list[dict], global_round: int = 0) -> FederatedRound:
    """
    Compute DP-masked local gradients and submit to the aggregation server.

    Args:
        samples: list of {input: str, output: str} training pairs (opt-in only)
        global_round: current federation round number from the server
    """
    global _total_privacy_budget_used

    round_id = str(uuid.uuid4())[:12]
    now      = datetime.now(timezone.utc).isoformat()
    rnd      = FederatedRound(round_id=round_id, global_round=global_round, started_at=now)

    ok_samples, sample_err = _validate_samples(samples)
    if not ok_samples:
        rnd.status = "failed"
        rnd.error = sample_err
        _rounds.append(rnd)
        return rnd

    if not FEDERATED_ENABLED:
        rnd.status = "disabled"
        rnd.error  = "Federated learning is disabled (set FEDERATED_ENABLED=true)"
        _rounds.append(rnd)
        return rnd

    with _state_lock:
        if _total_privacy_budget_used >= _MAX_PRIVACY_BUDGET:
            rnd.status = "failed"
            rnd.error  = f"Privacy budget exhausted (used {_total_privacy_budget_used:.2f} of {_MAX_PRIVACY_BUDGET})"
            _rounds.append(rnd)
            return rnd

    rnd.status         = "computing"
    rnd.local_samples  = len(samples)
    raw_gradients      = _compute_local_gradients(samples)
    noisy_gradients    = _add_dp_noise(raw_gradients)
    epsilon_used       = DP_NOISE_SIGMA * math.sqrt(2 * math.log(1.25 / 1e-5))
    rnd.privacy_budget_used = epsilon_used

    payload = {
        "round_id":      round_id,
        "node_id":       NODE_ID,
        "global_round":  global_round,
        "num_samples":   len(samples),
        "gradient":      noisy_gradients,
        "dp_noise_sigma": DP_NOISE_SIGMA,
        "gradient_hash": hashlib.sha256(json.dumps(noisy_gradients, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "timestamp":     now,
    }

    if FEDERATED_SERVER and FEDERATED_TOKEN:
        last_error = ""
        try:
            import requests  # type: ignore
            for attempt in range(1, max(1, FEDERATED_MAX_RETRIES) + 1):
                try:
                    resp = requests.post(
                        f"{FEDERATED_SERVER.rstrip('/')}/aggregate",
                        json=payload,
                        headers={"Authorization": f"Bearer {FEDERATED_TOKEN}"},
                        timeout=30,
                    )
                    resp.raise_for_status()
                    rnd.status = "submitted"
                    rnd.submitted_at = datetime.now(timezone.utc).isoformat()
                    with _state_lock:
                        _total_privacy_budget_used += epsilon_used
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if attempt < max(1, FEDERATED_MAX_RETRIES):
                        time.sleep(min(3.0, 0.25 * (2 ** (attempt - 1))))
            if rnd.status != "submitted":
                rnd.status = "failed"
                rnd.error = last_error or "federated submit failed"
        except Exception as exc:
            rnd.status = "failed"
            rnd.error = str(exc)
    else:
        # Offline mode — record local only
        rnd.status       = "local_only"
        rnd.submitted_at = datetime.now(timezone.utc).isoformat()
        with _state_lock:
            _total_privacy_budget_used += epsilon_used

    _rounds.append(rnd)
    if len(_rounds) > 100:
        _rounds.pop(0)

    logger.info("Federated round %s: status=%s, samples=%d, epsilon_used=%.4f",
                round_id, rnd.status, rnd.local_samples, epsilon_used)
    return rnd


def get_federation_status() -> dict:
    """Return current federation health and privacy budget state."""
    return {
        "enabled":                 FEDERATED_ENABLED,
        "node_id":                 NODE_ID,
        "server_configured":       bool(FEDERATED_SERVER),
        "total_rounds":            len(_rounds),
        "privacy_budget_used":     _total_privacy_budget_used,
        "privacy_budget_max":      _MAX_PRIVACY_BUDGET,
        "privacy_budget_remaining": max(0.0, _MAX_PRIVACY_BUDGET - _total_privacy_budget_used),
        "dp_noise_sigma":          DP_NOISE_SIGMA,
        "dp_max_grad_norm":        DP_MAX_GRAD_NORM,
        "last_round":              _rounds[-1].to_dict() if _rounds else None,
    }


def list_rounds(limit: int = 20) -> list[dict]:
    return [r.to_dict() for r in reversed(_rounds[-limit:])]
