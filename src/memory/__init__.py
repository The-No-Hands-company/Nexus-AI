"""
src/memory/ — Modularised memory package

Re-exports everything from src/memory.py so existing imports
(e.g. ``from .memory import add_memory``) still resolve correctly
now that memory/ is a package directory.

Modules:
    episodic.py  — event-based timeline (episodic) memory
"""

# Re-export all public symbols from the original memory.py module.
# Important: load it under a ``src.*`` module name so relative imports
# inside memory.py (e.g. ``from .db import ...``) continue to work.
import importlib.util as _ilu
import os as _os
import sys as _sys

_memory_py = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "memory.py")
_spec = _ilu.spec_from_file_location("src._memory_legacy", _memory_py)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load memory module from {_memory_py}")

_mod = _ilu.module_from_spec(_spec)
_sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

# Expose every public symbol so ``from src.memory import add_memory`` works.
add_memory = _mod.add_memory
get_memory_context = _mod.get_memory_context
summarize_history = _mod.summarize_history
delete_all = _mod.delete_all
get_all = _mod.get_all
get_semantic_memory = _mod.get_semantic_memory
get_semantic_memory_filtered = _mod.get_semantic_memory_filtered
prune_old_memories = _mod.prune_old_memories
add_semantic_memory = _mod.add_semantic_memory
get_episodic_timeline = _mod.get_episodic_timeline
export_memory_bundle = _mod.export_memory_bundle
import_memory_bundle = _mod.import_memory_bundle

__all__ = [
    "add_memory",
    "get_memory_context",
    "summarize_history",
    "delete_all",
    "get_all",
    "get_semantic_memory",
    "get_semantic_memory_filtered",
    "prune_old_memories",
    "add_semantic_memory",
    "get_episodic_timeline",
    "export_memory_bundle",
    "import_memory_bundle",
]
