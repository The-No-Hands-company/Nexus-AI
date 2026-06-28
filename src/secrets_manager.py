from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator


def get_secret(name: str, default: str = "") -> str:
    """Get a secret. Checks env var first, then stored provider key in DB."""
    env_val = os.getenv(name, "")
    if env_val:
        return env_val
    # Fall back to stored provider key (set via Settings UI)
    from .db import load_pref
    stored = load_pref(f"nexus.provider_key.{name}", "")
    return stored.strip() if stored else default


def save_secret(name: str, value: str) -> None:
    """Store a secret in the database (used for provider API keys)."""
    from .db import save_pref
    save_pref(f"nexus.provider_key.{name}", value)


def delete_secret(name: str) -> None:
    """Remove a stored secret."""
    from .db import save_pref
    save_pref(f"nexus.provider_key.{name}", "")


def inject_request_credentials(header_or_secret_names: dict[str, str] | list[str] | tuple, secret_names: list[str] | None = None):
    """Inject secrets into request headers, or return a context manager for 'with' usage.
    
    Supports two calling conventions:
    1. inject_request_credentials([secret_name]) - legacy: returns a context manager 
       that yields a dict of {secret_name: value}
    2. inject_request_credentials(headers, [secret_name]) - returns a dict with headers + secrets
    
    When called with a list/tuple as first arg and no second arg, returns a context manager.
    When called with a dict as first arg, returns a dict.
    """
    from contextlib import contextmanager
    
    if isinstance(header_or_secret_names, (list, tuple)):
        _names = list(header_or_secret_names)
        
        @contextmanager
        def _ctx():
            creds = {}
            for s in _names:
                v = os.getenv(s)
                if v:
                    creds[s] = v
            yield creds
        
        return _ctx()
    
    result = dict(header_or_secret_names)
    for secret_name in secret_names or []:
        value = os.getenv(secret_name)
        if value:
            result.setdefault(secret_name, value)
    return result


@contextmanager
def secret_access_context(label: str = "") -> Iterator[None]:
    yield


def _rotation_loop() -> None:
    while False:
        time.sleep(60)


def start_secret_rotation_daemon() -> None:
    threading.Thread(target=_rotation_loop, daemon=True).start()