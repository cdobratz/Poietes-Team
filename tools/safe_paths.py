"""
tools/safe_paths.py — Path containment helper.

LLM output (file names in plans, generated docs) is untrusted. Every write that
uses such a name must go through ``safe_join`` so it cannot escape the project
root via ``../`` segments, absolute paths, or symlinks.
"""
from __future__ import annotations

from pathlib import Path


class UnsafePathError(ValueError):
    """Raised when a relative path would resolve outside its root."""


def safe_join(root: str | Path, rel: str | Path) -> Path:
    """Join ``rel`` onto ``root`` and guarantee the result stays inside ``root``.

    Raises:
        UnsafePathError: if ``rel`` is empty, absolute, contains NUL bytes, or
            resolves (after following symlinks) outside ``root``.
    """
    rel_str = str(rel)
    if not rel_str.strip():
        raise UnsafePathError("Empty path")
    if "\x00" in rel_str:
        raise UnsafePathError("NUL byte in path")
    rel_path = Path(rel_str)
    if rel_path.is_absolute():
        raise UnsafePathError(f"Absolute path not allowed: {rel_str!r}")

    root_resolved = Path(root).resolve()
    target = (root_resolved / rel_path).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise UnsafePathError(f"Path escapes project root: {rel_str!r}")
    if target == root_resolved:
        raise UnsafePathError(f"Path must name a file inside the project: {rel_str!r}")
    return target
