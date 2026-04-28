"""src/deployment_profiles.py — Runtime deployment profile manager for Nexus AI.

Profiles (dev / staging / prod / enterprise / self-hosted) define environment-
specific tuning: log level, rate limits, allowed providers, safety strictness,
feature flags, and resource caps.  The active profile is chosen by the
NEXUS_PROFILE environment variable (default: dev).

Usage:
    from src.deployment_profiles import get_profile, apply_profile

    profile = get_profile()   # reads NEXUS_PROFILE env var
    apply_profile(profile)    # sets derived env vars in os.environ
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Profile definition ────────────────────────────────────────────────────────

@dataclass
class DeploymentProfile:
    name: str
    log_level: str                          = "INFO"
    debug: bool                             = False
    rate_limit_cooldown_s: int              = 60
    max_tokens_default: int                 = 4096
    max_context_messages: int               = 50
    allowed_providers: list[str]            = field(default_factory=list)
    safety_strictness: str                  = "standard"   # "permissive" | "standard" | "strict"
    hitl_mode: str                          = "off"         # "off" | "warn" | "block"
    enable_telemetry: bool                  = True
    enable_streaming: bool                  = True
    enable_autonomy: bool                   = True
    enable_benchmarks: bool                 = True
    enable_admin_routes: bool               = True
    cors_origins: list[str]                 = field(default_factory=lambda: ["*"])
    worker_concurrency: int                 = 4
    db_pool_size: int                       = 5
    redis_required: bool                    = False
    extra: dict[str, Any]                   = field(default_factory=dict)

    def to_env(self) -> dict[str, str]:
        """Return a flat dict of env-var overrides derived from this profile."""
        return {
            "LOG_LEVEL":               self.log_level,
            "DEBUG":                   "1" if self.debug else "0",
            "RATE_LIMIT_COOLDOWN":     str(self.rate_limit_cooldown_s),
            "MAX_TOKENS_DEFAULT":      str(self.max_tokens_default),
            "MAX_CONTEXT_MESSAGES":    str(self.max_context_messages),
            "SAFETY_STRICTNESS":       self.safety_strictness,
            "HITL_MODE":               self.hitl_mode,
            "ENABLE_TELEMETRY":        "1" if self.enable_telemetry else "0",
            "ENABLE_STREAMING":        "1" if self.enable_streaming else "0",
            "ENABLE_AUTONOMY":         "1" if self.enable_autonomy else "0",
            "ENABLE_BENCHMARKS":       "1" if self.enable_benchmarks else "0",
            "ENABLE_ADMIN_ROUTES":     "1" if self.enable_admin_routes else "0",
            "WORKER_CONCURRENCY":      str(self.worker_concurrency),
            "DB_POOL_SIZE":            str(self.db_pool_size),
            "REDIS_REQUIRED":          "1" if self.redis_required else "0",
        }


# ── Built-in profiles ─────────────────────────────────────────────────────────

_PROFILES: dict[str, DeploymentProfile] = {
    "dev": DeploymentProfile(
        name="dev",
        log_level="DEBUG",
        debug=True,
        rate_limit_cooldown_s=10,
        max_tokens_default=8192,
        max_context_messages=100,
        safety_strictness="permissive",
        hitl_mode="warn",
        enable_telemetry=False,
        cors_origins=["*"],
        worker_concurrency=2,
        db_pool_size=2,
    ),
    "staging": DeploymentProfile(
        name="staging",
        log_level="INFO",
        debug=False,
        rate_limit_cooldown_s=30,
        max_tokens_default=4096,
        max_context_messages=60,
        safety_strictness="standard",
        hitl_mode="warn",
        enable_telemetry=True,
        cors_origins=["*"],
        worker_concurrency=4,
        db_pool_size=5,
    ),
    "prod": DeploymentProfile(
        name="prod",
        log_level="WARNING",
        debug=False,
        rate_limit_cooldown_s=60,
        max_tokens_default=4096,
        max_context_messages=50,
        safety_strictness="strict",
        hitl_mode="block",
        enable_telemetry=True,
        cors_origins=[],  # set via CORS_ORIGINS env var in prod
        worker_concurrency=8,
        db_pool_size=10,
        redis_required=True,
    ),
    "self-hosted": DeploymentProfile(
        name="self-hosted",
        log_level="INFO",
        debug=False,
        rate_limit_cooldown_s=30,
        max_tokens_default=8192,
        max_context_messages=80,
        allowed_providers=["ollama"],
        safety_strictness="standard",
        hitl_mode="warn",
        enable_telemetry=False,
        cors_origins=["*"],
        worker_concurrency=4,
        db_pool_size=5,
        redis_required=False,
        extra={"local_only": True},
    ),
    "enterprise": DeploymentProfile(
        name="enterprise",
        log_level="WARNING",
        debug=False,
        rate_limit_cooldown_s=120,
        max_tokens_default=4096,
        max_context_messages=50,
        safety_strictness="strict",
        hitl_mode="block",
        enable_telemetry=True,
        cors_origins=[],
        worker_concurrency=16,
        db_pool_size=20,
        redis_required=True,
        extra={"sso_required": True, "audit_all_requests": True, "data_residency": True},
    ),
}

VALID_PROFILES = list(_PROFILES.keys())


# ── Public API ────────────────────────────────────────────────────────────────

def get_profile(name: str | None = None) -> DeploymentProfile:
    """Return the profile for *name* (or NEXUS_PROFILE env var, defaulting to 'dev')."""
    profile_name = (name or os.getenv("NEXUS_PROFILE", "dev")).lower().strip()
    if profile_name not in _PROFILES:
        logger.warning(
            "Unknown NEXUS_PROFILE=%r — falling back to 'dev'. Valid: %s",
            profile_name, ", ".join(VALID_PROFILES),
        )
        profile_name = "dev"
    return _PROFILES[profile_name]


def apply_profile(profile: DeploymentProfile | None = None) -> DeploymentProfile:
    """Apply *profile* env-var overrides to os.environ (only for unset vars).

    Variables already set in the environment take precedence so that explicit
    operator configuration is never silently overridden.
    """
    if profile is None:
        profile = get_profile()
    for key, value in profile.to_env().items():
        if not os.environ.get(key):
            os.environ[key] = value
    logger.info("Deployment profile applied: %s", profile.name)
    return profile


def list_profiles() -> list[dict[str, Any]]:
    """Return a summary of all built-in profiles."""
    return [
        {
            "name":             p.name,
            "log_level":        p.log_level,
            "debug":            p.debug,
            "safety_strictness": p.safety_strictness,
            "hitl_mode":        p.hitl_mode,
            "worker_concurrency": p.worker_concurrency,
            "redis_required":   p.redis_required,
        }
        for p in _PROFILES.values()
    ]


def get_profile_summary() -> dict[str, Any]:
    """Return the active profile name and key settings for health/info endpoints."""
    profile = get_profile()
    return {
        "active_profile": profile.name,
        "log_level":      profile.log_level,
        "safety":         profile.safety_strictness,
        "hitl_mode":      profile.hitl_mode,
        "telemetry":      profile.enable_telemetry,
        "redis_required": profile.redis_required,
    }
