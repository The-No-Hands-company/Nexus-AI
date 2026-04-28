from __future__ import annotations

"""Runtime feature-flag helpers backed by db.feature_flags."""

from . import db
from .config.feature_flags import DEFAULT_FLAGS


def bootstrap_default_flags() -> None:
    for name, cfg in DEFAULT_FLAGS.items():
        existing = db.load_feature_flag(name)
        if existing:
            continue
        db.upsert_feature_flag(
            name=name,
            enabled=bool(cfg.get("enabled", False)),
            description=str(cfg.get("description", "")),
        )


def is_enabled(name: str, default: bool = False) -> bool:
    row = db.load_feature_flag(name)
    if not row:
        return default
    return bool(row.get("enabled", False))


def set_flag(
    name: str,
    enabled: bool,
    description: str = "",
    rollout_percentage: int = 0,
    user_overrides: str = "{}",
    org_overrides: str = "{}",
    value: str = "",
) -> dict:
    return db.upsert_feature_flag(
        name=name,
        enabled=enabled,
        description=description,
        rollout_percentage=rollout_percentage,
        user_overrides=user_overrides,
        org_overrides=org_overrides,
        value=value,
    )


def list_flags() -> list[dict]:
    bootstrap_default_flags()
    return db.list_feature_flags()


def delete_flag(name: str) -> bool:
    return db.delete_feature_flag(name)
