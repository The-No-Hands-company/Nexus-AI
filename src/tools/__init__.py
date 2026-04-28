"""Tools package scaffold for Phase 2 refactor.

The concrete built-in tools implementation remains in src/tools_builtin.py
for compatibility while the canonical package path becomes src/tools/.
"""

from .builtin import dispatch_builtin

__all__ = ["dispatch_builtin"]
