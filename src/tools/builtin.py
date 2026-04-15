"""Compatibility bridge to built-in tools implementation.

Phase 2 introduces src/tools/ as the canonical import path while
preserving runtime behavior from src/tools_builtin.py.
"""

from ..tools_builtin import *  # noqa: F401,F403
