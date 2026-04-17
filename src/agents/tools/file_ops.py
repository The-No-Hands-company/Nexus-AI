"""
src/agents/tools/file_ops.py — Typed file operation wrappers

Thin typed wrappers around the tool_* file functions in tools_builtin.py,
with path safety enforcement (sandboxed to the working directory).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKDIR = os.environ.get("WORKDIR", "/tmp/nexus_workdir")


def _safe_path(path: str) -> str:
    """Resolve *path* relative to WORKDIR and reject traversal attempts."""
    resolved = Path(WORKDIR).joinpath(path).resolve()
    if not str(resolved).startswith(str(Path(WORKDIR).resolve())):
        raise PermissionError(f"Path traversal rejected: {path}")
    return str(resolved)


@dataclass
class FileInfo:
    path: str
    name: str
    size_bytes: int
    is_dir: bool
    modified_at: str


def read_file(path: str) -> str:
    """
    Read a file from the working directory.

    Thin wrapper around tool_read_file with path safety.
    STUB: calls tool_read_file if available, else raises NotImplementedError.
    """
    safe = _safe_path(path)
    try:
        with open(safe, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found in workdir: {path}")


def write_file(path: str, content: str, overwrite: bool = True) -> str:
    """
    Write content to a file in the working directory.

    STUB: basic implementation — no versioning yet.
    """
    safe = _safe_path(path)
    os.makedirs(os.path.dirname(safe), exist_ok=True)
    if not overwrite and os.path.exists(safe):
        raise FileExistsError(f"File already exists and overwrite=False: {path}")
    with open(safe, "w", encoding="utf-8") as f:
        f.write(content)
    return safe


def list_files(directory: str = ".") -> list[FileInfo]:
    """
    List files in a directory within the working directory.

    STUB: raises NotImplementedError for full metadata.
    Returns basic listing.
    """
    safe = _safe_path(directory)
    if not os.path.isdir(safe):
        raise NotADirectoryError(f"Not a directory: {directory}")
    entries = []
    for name in sorted(os.listdir(safe)):
        full = os.path.join(safe, name)
        stat = os.stat(full)
        import datetime
        entries.append(FileInfo(
            path=os.path.join(directory, name),
            name=name,
            size_bytes=stat.st_size,
            is_dir=os.path.isdir(full),
            modified_at=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        ))
    return entries


def delete_file(path: str) -> bool:
    """Delete a file from the working directory. Returns True on success."""
    safe = _safe_path(path)
    if not os.path.exists(safe):
        return False
    os.remove(safe)
    return True


def move_file(src: str, dst: str) -> str:
    """
    Move a file within the working directory.

    STUB: raises NotImplementedError.
    """
    raise NotImplementedError(
        "move_file is not yet implemented. "
        "Planned: safe path check on both src and dst, then os.rename."
    )


def search_in_files(pattern: str, directory: str = ".", file_glob: str = "*") -> list[dict]:
    """
    Search for *pattern* (regex) in files matching *file_glob*.

    STUB: raises NotImplementedError.
    Implementation plan: pathlib glob + re.search per file + return [{file, line, text}].
    """
    raise NotImplementedError(
        "search_in_files is not yet implemented. "
        "Planned: pathlib glob + regex search across workdir files."
    )
