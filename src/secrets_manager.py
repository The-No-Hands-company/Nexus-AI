from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Iterator


def get_secret(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def inject_request_credentials(headers: dict[str, str], secret_names: list[str] | None = None) -> dict[str, str]:
    result = dict(headers)
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