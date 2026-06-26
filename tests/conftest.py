import os
import tempfile
import uuid as _uuid
import warnings
import logging

# Use a unique DB for each test session to avoid collisions between runs.
os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), f"nexus_test_{os.getpid()}_{_uuid.uuid4().hex[:8]}.db")

# Silence known third-party warning on Python 3.14+ from langsmith's
# optional pydantic.v1 compatibility layer. This warning is benign for
# Nexus AI test execution and can obscure real failures in CI logs.
warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
    category=UserWarning,
    module=r"langsmith\.schemas",
)

# FastAPI on Python 3.14 emits this deprecation from internals; keep test logs focused.
warnings.filterwarnings(
    "ignore",
    message=r"'asyncio\.iscoroutinefunction' is deprecated and slated for removal in Python 3\.16; use inspect\.iscoroutinefunction\(\) instead",
    category=DeprecationWarning,
)

# Transformers tokenizer initialization warning is non-actionable for these tests.
warnings.filterwarnings(
    "ignore",
    message=r"Deprecated in 0\.9\.0: WordPiece\.__init__ will not create from files anymore",
    category=DeprecationWarning,
)

# Prevent noisy debug-level close-session logs from writing during interpreter teardown.
for logger_name in ("httpcore", "httpx", "huggingface_hub", "huggingface_hub.utils._http"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)


import pytest
from fastapi.testclient import TestClient
from src.app import app

# Ensure projects table exists early (lifespan init may be deferred).
from src.db import init_projects_table
init_projects_table()


@pytest.fixture(autouse=True)
def _ensure_projects_table():
    """Ensure projects table exists before every test.

    The lifespan context manager initialises tables asynchronously and may
    not have run yet when TestClient is used outside of a live server.
    Additionally, some test modules may drop or modify tables, so we
    recreate them here to prevent cascading failures.
    """
    init_projects_table()


@pytest.fixture
def client():
    return TestClient(app)
