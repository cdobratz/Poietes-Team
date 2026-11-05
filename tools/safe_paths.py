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


def _check_path_text(raw: str) -> None:
    if not raw.strip():
        raise UnsafePathError("Empty path")
    if "\x00" in raw:
        raise UnsafePathError("NUL byte in path")


def _is_inside(root_resolved: Path, target: Path) -> bool:
    return target == root_resolved or root_resolved in target.parents


def path_stays_inside(root: str | Path, candidate: str | Path) -> bool:
    """True when ``candidate`` resolves inside ``root`` (symlinks included).

    ``candidate`` is already a path, not a user string to join onto ``root``.
    """
    if root is None or not str(root).strip():
        return False
    root_resolved = Path(root).resolve()
    try:
        target = Path(candidate).resolve()
    except OSError:
        return False
    return _is_inside(root_resolved, target)


def safe_join(root: str | Path, rel: str | Path) -> Path:
    """Join ``rel`` onto ``root`` and guarantee the result stays inside ``root``.

    Raises:
        UnsafePathError: if ``rel`` is empty, absolute, contains NUL bytes, or
            resolves (after following symlinks) outside ``root``.
    """
    rel_str = str(rel)
    _check_path_text(rel_str)
    rel_path = Path(rel_str)
    if rel_path.is_absolute():
        raise UnsafePathError(f"Absolute path not allowed: {rel_str!r}")

    root_resolved = Path(root).resolve()
    target = (root_resolved / rel_path).resolve()
    if not _is_inside(root_resolved, target):
        raise UnsafePathError(f"Path escapes project root: {rel_str!r}")
    if target == root_resolved:
        raise UnsafePathError(f"Path must name a file inside the project: {rel_str!r}")
    return target


def resolve_within_root(
    root: str | Path,
    user_path: str | Path,
    *,
    allow_root: bool = False,
) -> Path:
    """Resolve ``user_path`` and require it to stay inside ``root``.

    Relative paths are joined onto ``root`` (same containment rules as
    ``safe_join``, including symlink resolution). Absolute paths are accepted
    only when they already resolve inside ``root``. ``allow_root`` permits the
    workspace directory itself, which file-edit helpers reject.
    """
    if root is None or not str(root).strip():
        raise UnsafePathError("Workspace root is not configured")
    raw = str(user_path)
    _check_path_text(raw)

    root_resolved = Path(root).resolve()
    candidate = Path(raw)
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (root_resolved / candidate).resolve()

    if not _is_inside(root_resolved, target):
        raise UnsafePathError(f"Path escapes workspace root: {raw!r}")
    if target == root_resolved and not allow_root:
        raise UnsafePathError(f"Path must name an entry inside the workspace: {raw!r}")
    return target
