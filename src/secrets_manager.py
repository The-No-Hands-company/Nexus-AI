"""Secrets management for Nexus AI.

Provides a unified ``get_secret(name)`` API that resolves secrets from:
  1. HashiCorp Vault (when VAULT_ADDR + VAULT_TOKEN are set)
  2. AWS Secrets Manager (when AWS_REGION + AWS_SECRET_PREFIX are set)
  3. Encrypted local .env / environment variables (always available as fallback)

Secrets are cached in-process with a configurable TTL to avoid hammering the
secrets backend on every request.

Environment variables:
    VAULT_ADDR         — Vault server address (e.g. http://vault:8200)
    VAULT_TOKEN        — Vault root/app token
    VAULT_SECRET_PATH  — KV v2 path prefix (default: nexus-ai/data/secrets)
    AWS_REGION         — AWS region for Secrets Manager
    AWS_SECRET_PREFIX  — prefix for secret names (default: nexus-ai/)
    SECRET_CACHE_TTL   — seconds to cache resolved secrets (default: 300)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("nexus.secrets")

_CACHE_TTL = int(os.getenv("SECRET_CACHE_TTL", "300"))
_VAULT_ADDR = os.getenv("VAULT_ADDR", "")
_VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")
_VAULT_PATH = os.getenv("VAULT_SECRET_PATH", "nexus-ai/data/secrets")
_AWS_REGION = os.getenv("AWS_REGION", "")
_AWS_PREFIX = os.getenv("AWS_SECRET_PREFIX", "nexus-ai/")

# ── In-memory secret cache ────────────────────────────────────────────────────

_secret_cache: dict[str, tuple[Any, float]] = {}  # name -> (value, expires_at)
_cache_lock = threading.Lock()
_access_log: list[dict] = []  # lightweight in-process audit trail
_rotation_started = False
_rotation_lock = threading.Lock()


def _cache_get(name: str) -> Any:
    with _cache_lock:
        entry = _secret_cache.get(name)
        if entry and time.time() < entry[1]:
            return entry[0]
    return None


def _cache_set(name: str, value: Any) -> None:
    with _cache_lock:
        _secret_cache[name] = (value, time.time() + _CACHE_TTL)


def _record_access(name: str, source: str) -> None:
    """Append an access record to the in-process audit trail."""
    entry = {"name": name, "source": source, "ts": time.time()}
    with _cache_lock:
        _access_log.append(entry)
        if len(_access_log) > 500:
            _access_log.pop(0)
    try:
        from .observability import write_audit_log
        write_audit_log(
            actor="system",
            action="secret_access",
            resource=name,
            result="ok",
            metadata={"source": source},
        )
    except Exception:
        pass


# ── Vault backend ─────────────────────────────────────────────────────────────

def _get_from_vault(name: str) -> Any:
    """Fetch a secret from HashiCorp Vault KV v2."""
    if not _VAULT_ADDR or not _VAULT_TOKEN:
        return None
    try:
        import httpx  # type: ignore
        url = f"{_VAULT_ADDR}/v1/{_VAULT_PATH}/{name}"
        resp = httpx.get(
            url,
            headers={"X-Vault-Token": _VAULT_TOKEN},
            timeout=5.0,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        # KV v2 wraps data in .data.data
        value = data.get("data", {}).get("data", {}).get("value")
        if value is None:
            value = data.get("data", {}).get("value")
        return value
    except Exception as exc:
        logger.warning("vault_fetch_error", name=name, error=str(exc))
        return None


# ── AWS Secrets Manager backend ───────────────────────────────────────────────

def _get_from_aws(name: str) -> Any:
    """Fetch a secret from AWS Secrets Manager."""
    if not _AWS_REGION:
        return None
    try:
        import boto3  # type: ignore
        client = boto3.client("secretsmanager", region_name=_AWS_REGION)
        full_name = f"{_AWS_PREFIX}{name}" if not name.startswith(_AWS_PREFIX) else name
        resp = client.get_secret_value(SecretId=full_name)
        secret_string = resp.get("SecretString")
        if secret_string:
            try:
                parsed = json.loads(secret_string)
                return parsed.get("value", parsed)
            except json.JSONDecodeError:
                return secret_string
        binary = resp.get("SecretBinary")
        if binary:
            return binary.decode("utf-8")
        return None
    except Exception as exc:
        if "ResourceNotFoundException" in str(type(exc)):
            return None
        logger.warning("aws_secrets_fetch_error", name=name, error=str(exc))
        return None


# ── Environment / .env fallback ───────────────────────────────────────────────

def _get_from_env(name: str) -> Any:
    """Look up a secret from environment variables.

    Maps snake_case name → UPPER_SNAKE_CASE env var.
    e.g. "jwt_secret" → JWT_SECRET
    """
    env_name = name.upper().replace("-", "_")
    return os.getenv(env_name)


# ── Public API ────────────────────────────────────────────────────────────────

def get_secret(name: str, default: Any = None) -> Any:
    """Resolve a named secret from the configured backend(s).

    Resolution order:
    1. In-process cache
    2. HashiCorp Vault (if VAULT_ADDR configured)
    3. AWS Secrets Manager (if AWS_REGION configured)
    4. Environment variable
    5. ``default``

    Returns the secret value or ``default`` if not found.
    Never raises.
    """
    # 1. Cache
    cached = _cache_get(name)
    if cached is not None:
        return cached

    # 2. Vault
    if _VAULT_ADDR:
        value = _get_from_vault(name)
        if value is not None:
            _cache_set(name, value)
            _record_access(name, "vault")
            return value

    # 3. AWS Secrets Manager
    if _AWS_REGION:
        value = _get_from_aws(name)
        if value is not None:
            _cache_set(name, value)
            _record_access(name, "aws")
            return value

    # 4. Environment variable
    value = _get_from_env(name)
    if value is not None:
        _cache_set(name, value)
        _record_access(name, "env")
        return value

    return default


def invalidate_secret(name: str) -> None:
    """Remove a secret from the in-process cache to force a fresh fetch."""
    with _cache_lock:
        _secret_cache.pop(name, None)


def get_secret_access_log(limit: int = 100) -> list[dict]:
    """Return the most recent secret access log entries."""
    with _cache_lock:
        return list(_access_log[-limit:])


def rotate_secret_in_cache(name: str, new_value: Any) -> None:
    """Inject a rotated secret value directly into the cache (e.g. after rotation event)."""
    _cache_set(name, new_value)
    logger.info("secret_rotated_in_cache", name=name)


def start_secret_rotation_daemon(secret_names: list[str] | None = None, interval_seconds: int | None = None) -> bool:
    """Start a background daemon that refreshes/invalidate configured secrets on interval.

    Controlled by env:
      SECRET_ROTATION_INTERVAL_SECONDS (default 3600)
      ROTATING_SECRETS (comma-separated secret names)
    """
    global _rotation_started
    with _rotation_lock:
        if _rotation_started:
            return False
        _rotation_started = True

    secrets_to_rotate = secret_names or [
        s.strip() for s in os.getenv("ROTATING_SECRETS", "JWT_SECRET").split(",") if s.strip()
    ]
    interval = int(interval_seconds or int(os.getenv("SECRET_ROTATION_INTERVAL_SECONDS", "3600")))

    def _worker() -> None:
        while True:
            try:
                for name in secrets_to_rotate:
                    invalidate_secret(name)
                    get_secret(name)
                    logger.info("secret_rotation_refresh", name=name)
            except Exception:
                pass
            time.sleep(max(60, interval))

    t = threading.Thread(target=_worker, daemon=True, name="nexus-secret-rotation")
    t.start()
    return True


def _get_env_crypto_key() -> bytes | None:
    key = os.getenv("ENV_STORE_KEY", "").strip()
    if not key:
        return None
    try:
        return key.encode("utf-8")
    except Exception:
        return None


def _env_store_path() -> str:
    return os.getenv("ENV_STORE_PATH", "/tmp/nexus_env_store.enc")


def save_encrypted_env_var(name: str, value: str) -> bool:
    """Persist an env-style key/value in encrypted local store when available."""
    key = _get_env_crypto_key()
    if not key:
        return False
    try:
        from cryptography.fernet import Fernet  # type: ignore

        f = Fernet(key)
        path = _env_store_path()
        payload: dict[str, str] = {}
        if os.path.exists(path):
            data = open(path, "rb").read()
            payload = json.loads(f.decrypt(data).decode("utf-8"))
        payload[name] = value
        enc = f.encrypt(json.dumps(payload).encode("utf-8"))
        open(path, "wb").write(enc)
        return True
    except Exception:
        return False


def load_encrypted_env_var(name: str, default: Any = None) -> Any:
    """Load a key from encrypted local env store."""
    key = _get_env_crypto_key()
    if not key:
        return default
    try:
        from cryptography.fernet import Fernet  # type: ignore

        path = _env_store_path()
        if not os.path.exists(path):
            return default
        f = Fernet(key)
        data = open(path, "rb").read()
        payload = json.loads(f.decrypt(data).decode("utf-8"))
        return payload.get(name, default)
    except Exception:
        return default


@contextmanager
def inject_request_credentials(secret_names: list[str]) -> dict[str, Any]:
    """Resolve a set of secrets for one request scope only.

    Returns a dict of requested credentials and does not persist values.
    """
    creds = {name: get_secret(name) for name in secret_names}
    try:
        yield creds
    finally:
        # Best effort cleanup for request scope variables.
        for k in list(creds.keys()):
            creds[k] = None


def secrets_health() -> dict:
    """Return the health / configuration state of each secret backend."""
    backends: dict[str, dict] = {}

    if _VAULT_ADDR:
        try:
            import httpx  # type: ignore
            resp = httpx.get(f"{_VAULT_ADDR}/v1/sys/health", timeout=3.0)
            backends["vault"] = {
                "configured": True,
                "reachable": resp.is_success,
                "status": resp.json().get("initialized", False),
            }
        except Exception as exc:
            backends["vault"] = {"configured": True, "reachable": False, "error": str(exc)}
    else:
        backends["vault"] = {"configured": False}

    backends["aws"] = {"configured": bool(_AWS_REGION), "region": _AWS_REGION or None}
    backends["env"] = {"configured": True}

    return {
        "backends": backends,
        "cached_secrets": len(_secret_cache),
        "cache_ttl": _CACHE_TTL,
    }
