import warnings

# Silence known third-party warning on Python 3.14+ from langsmith's
# optional pydantic.v1 compatibility layer. This warning is benign for
# Nexus AI test execution and can obscure real failures in CI logs.
warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
    category=UserWarning,
    module=r"langsmith\.schemas",
)
