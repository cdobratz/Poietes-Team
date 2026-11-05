"""
tools/fs_stats.py — Shared directory walk and text-file statistics.

MonitorAgent and FilesystemAgent both count lines and skip the same heavy
directories. Callers still decide which extensions and thresholds they report.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from tools.safe_paths import path_stays_inside

logger = logging.getLogger(__name__)

# Directories that must not be scanned (dependencies, VCS, build output).
IGNORE_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "dist", "build"})

MONITOR_TEXT_EXTS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".cs",
})

# Extensions FilesystemAgent counts lines for.
FS_TEXT_EXTS = frozenset({
    ".py", ".js", ".ts", ".txt", ".md", ".yaml", ".yml", ".json", ".sh",
})


def is_ignored(path: Path, ignore_dirs: frozenset[str] | set[str] = IGNORE_DIRS) -> bool:
    """True when any path segment is an ignored directory name."""
    return any(part in ignore_dirs for part in path.parts)


def read_text_lines(path: Path) -> list[str] | None:
    """Return split lines, or None if the file cannot be read as text."""
    try:
        return path.read_text(errors="ignore").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def _on_walk_error(err: OSError) -> None:
    logger.debug("Skipping %s: %s", getattr(err, "filename", "?"), err)


def walk_tree(
    root: Path,
    *,
    ignore_dirs: frozenset[str] | set[str] = IGNORE_DIRS,
    include_hidden: bool = True,
) -> list[Path]:
    """Files and directories under ``root`` (not ``root`` itself).

    Ignored directories are not descended. Symlinks are not followed, and any
    entry that resolves outside ``root`` is dropped.
    """
    if not root.exists():
        return []
    root_resolved = root.resolve()
    found: list[Path] = []

    def _kept(name: str, child: Path) -> bool:
        if name in ignore_dirs:
            return False
        if not include_hidden and name.startswith("."):
            return False
        # Never follow symlinks: a link can point outside the workspace.
        if child.is_symlink():
            return False
        return path_stays_inside(root_resolved, child)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_on_walk_error):
        current = Path(dirpath)
        dirnames[:] = [d for d in dirnames if _kept(d, current / d)]
        if current != root and _kept(current.name, current):
            found.append(current)
        for name in filenames:
            child = current / name
            if _kept(name, child):
                found.append(child)
    return found


def scan_project_stats(path: str) -> dict:
    """File / line / TODO / large-file stats used by MonitorAgent."""
    root = Path(path)
    if not root.exists():
        return {"error": f"Path not found: {path}"}

    stats: dict = {
        "total_files": 0,
        "total_lines": 0,
        "todo_count": 0,
        "large_files": [],
        "file_types": {},
    }

    for item in walk_tree(root, include_hidden=True):
        if not item.is_file():
            continue
        stats["total_files"] += 1
        ext = item.suffix.lower()
        stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1
        if ext not in MONITOR_TEXT_EXTS:
            continue
        lines = read_text_lines(item)
        if lines is None:
            continue
        count = len(lines)
        stats["total_lines"] += count
        stats["todo_count"] += sum(
            1 for line in lines if "TODO" in line or "FIXME" in line or "HACK" in line
        )
        if count > 500:
            stats["large_files"].append({
                "file": str(item.relative_to(root)),
                "lines": count,
            })
    return stats
