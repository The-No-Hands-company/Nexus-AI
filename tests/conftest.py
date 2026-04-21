import warnings
import logging

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
