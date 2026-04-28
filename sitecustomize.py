import warnings

# Suppress a known benign warning emitted by langsmith on Python 3.14+.
# This runs at interpreter startup when the repository root is on PYTHONPATH.
warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
    category=UserWarning,
)
