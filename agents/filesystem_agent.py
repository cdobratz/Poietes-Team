"""
agents/filesystem_agent.py — Agent for scanning directories inside a workspace.

Every path is resolved against a workspace root (``settings.workspace.root``,
or the project path for supervisor/Telegram tasks) and rejected when it escapes,
using the same containment rules as ``tools.safe_paths``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agents.base import AgentResult, BaseAgent
from config.loader import Project, Settings
from tools.fs_stats import FS_TEXT_EXTS, IGNORE_DIRS, is_ignored, read_text_lines, walk_tree
from tools.safe_paths import UnsafePathError, path_stays_inside, resolve_within_root

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Structured file metadata."""
    path: str
    size: int
    modified: str
    is_dir: bool
    extension: str | None = None
    line_count: int | None = None


@dataclass
class ScanResult:
    """Result from a directory scan operation."""
    path: str
    files: list[FileInfo] = field(default_factory=list)
    total_files: int = 0
    total_dirs: int = 0
    total_size: int = 0


@dataclass
class SearchResult:
    """Result from a content search operation."""
    path: str
    matches: list[dict] = field(default_factory=list)
    files_matched: int = 0
    total_matches: int = 0


class FilesystemAgent(BaseAgent):
    """
    Agent for filesystem operations inside a configured workspace.

    Supervisor (including Telegram ``/run`` plans) calls ``run_task``. Those
    paths are limited to the project directory. ``main.py fs`` commands have
    no project, so they require ``workspace.root``.
    """

    name = "filesystem"

    def __init__(self, settings: Settings, memory=None, messenger=None):
        super().__init__(settings, memory, messenger)

    # ── Sandbox ───────────────────────────────────────────────────────────────

    def effective_root(self, project: Project | None = None) -> str:
        """Directory that user-supplied paths must stay inside.

        A project path is the sandbox for agent tasks. When ``workspace.root``
        is also set, the project path must already sit inside it. CLI calls
        have no project and require ``workspace.root``.
        """
        configured = (self.settings.workspace.root or "").strip()
        project_path = (project.path or "").strip() if project is not None else ""
        if project_path and configured:
            project_resolved = Path(project_path).resolve()
            workspace = Path(configured).resolve()
            if project_resolved != workspace and workspace not in project_resolved.parents:
                raise UnsafePathError(
                    f"Project path {project_path!r} is outside workspace.root {configured!r}"
                )
            return str(project_resolved)
        if project_path:
            return str(Path(project_path).resolve())
        if configured:
            return str(Path(configured).resolve())
        raise UnsafePathError(
            "Workspace root is not configured. Set workspace.root or a project path."
        )

    def _root_for_call(self, root: str | None) -> str:
        if root is not None and str(root).strip():
            return str(root)
        return self.effective_root(None)

    def _resolve(self, path: str, root: str | None, *, allow_root: bool = True) -> Path:
        return resolve_within_root(self._root_for_call(root), path, allow_root=allow_root)

    @staticmethod
    def _check_pattern(pattern: str | None) -> None:
        if not pattern:
            return
        if "\x00" in pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise UnsafePathError(f"Unsafe glob pattern: {pattern!r}")

    def _line_count(self, path: Path) -> int | None:
        if path.suffix not in FS_TEXT_EXTS:
            return None
        lines = read_text_lines(path)
        if lines is None:
            return None
        return len(lines)

    # ── Core Operations ───────────────────────────────────────────────────────

    def scan_directory(
        self,
        path: str,
        pattern: str | None = None,
        include_hidden: bool = False,
        root: str | None = None,
    ) -> ScanResult:
        """
        Recursively scan a directory inside the workspace, optionally filtering
        by glob pattern.
        """
        result = ScanResult(path=path)
        base_root = self._root_for_call(root)
        base_path = resolve_within_root(base_root, path, allow_root=True)

        if not base_path.exists():
            logger.warning(f"Path does not exist: {path}")
            return result

        if not base_path.is_dir():
            logger.warning(f"Path is not a directory: {path}")
            return result

        self._check_pattern(pattern)

        try:
            if pattern:
                candidates = list(base_path.glob(pattern))
            else:
                candidates = walk_tree(base_path, include_hidden=include_hidden)

            for item in candidates:
                if is_ignored(item) or not path_stays_inside(base_root, item):
                    continue
                if not include_hidden:
                    try:
                        rel_parts = item.resolve().relative_to(Path(base_root).resolve()).parts
                    except ValueError:
                        continue
                    if any(part.startswith(".") for part in rel_parts):
                        continue

                try:
                    stat = item.stat()
                    is_dir = item.is_dir()

                    file_info = FileInfo(
                        path=str(item),
                        size=stat.st_size if not is_dir else 0,
                        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        is_dir=is_dir,
                        extension=item.suffix if not is_dir else None,
                    )

                    if not is_dir:
                        file_info.line_count = self._line_count(item)

                    result.files.append(file_info)

                    if is_dir:
                        result.total_dirs += 1
                    else:
                        result.total_files += 1
                        result.total_size += stat.st_size

                except (PermissionError, OSError) as e:
                    logger.debug(f"Skipping {item}: {e}")
                    continue

        except (OSError, UnsafePathError) as e:
            logger.error(f"Error scanning {path}: {e}")

        return result

    def search_files(
        self,
        path: str,
        query: str,
        file_pattern: str | None = None,
        case_sensitive: bool = False,
        include_context: int = 2,
        root: str | None = None,
    ) -> SearchResult:
        """Search for text content in files inside the workspace."""
        result = SearchResult(path=path)
        base_root = self._root_for_call(root)
        base_path = resolve_within_root(base_root, path, allow_root=True)

        if not base_path.exists() or not base_path.is_dir():
            logger.warning(f"Invalid search path: {path}")
            return result

        self._check_pattern(file_pattern)

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(query, flags)
        except re.error as e:
            logger.error(f"Invalid regex pattern '{query}': {e}")
            return result

        search_exts = FS_TEXT_EXTS | {".html", ".css"}
        files_to_search = []
        for item in walk_tree(base_path, include_hidden=True):
            if not item.is_file() or is_ignored(item) or not path_stays_inside(base_root, item):
                continue
            if file_pattern:
                if item.match(file_pattern):
                    files_to_search.append(item)
            elif item.suffix in search_exts:
                files_to_search.append(item)

        for file_path in files_to_search:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                file_matches = []
                for line_num, line in enumerate(lines, 1):
                    if regex.search(line):
                        file_matches.append({
                            "line": line_num,
                            "content": line.rstrip(),
                        })
                        result.total_matches += 1

                if file_matches:
                    matches_with_context = []
                    for match in file_matches:
                        start = max(0, match["line"] - include_context - 1)
                        end = min(len(lines), match["line"] + include_context)
                        context = {
                            "before": [lines[i].rstrip() for i in range(start, match["line"] - 1)],
                            "match": match["content"],
                            "after": [lines[i].rstrip() for i in range(match["line"], end)],
                        }
                        matches_with_context.append({
                            "line": match["line"],
                            "content": match["content"],
                            "context": context,
                        })

                    result.matches.append({
                        "file": str(file_path),
                        "matches": matches_with_context,
                    })
                    result.files_matched += 1

            except (PermissionError, OSError, UnicodeDecodeError) as e:
                logger.debug(f"Skipping {file_path}: {e}")
                continue

        return result

    def get_file_info(self, path: str, root: str | None = None) -> FileInfo | None:
        """Get detailed metadata for a single file or directory inside the workspace."""
        p = self._resolve(path, root, allow_root=True)

        if not p.exists():
            logger.warning(f"Path does not exist: {path}")
            return None

        try:
            stat = p.stat()
            is_dir = p.is_dir()

            info = FileInfo(
                path=str(p.absolute()),
                size=stat.st_size if not is_dir else 0,
                modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                is_dir=is_dir,
                extension=p.suffix if not is_dir else None,
            )

            if not is_dir:
                info.line_count = self._line_count(p)

            return info

        except OSError as e:
            logger.error(f"Error getting info for {path}: {e}")
            return None

    def list_tree(
        self,
        path: str,
        max_depth: int = 3,
        include_hidden: bool = False,
        root: str | None = None,
    ) -> list[dict]:
        """Get directory tree structure as nested dictionaries, inside the workspace."""
        base_root = self._root_for_call(root)
        base_path = resolve_within_root(base_root, path, allow_root=True)

        if not base_path.exists() or not base_path.is_dir():
            logger.warning(f"Invalid directory: {path}")
            return []

        def build_tree(current_path: Path, depth: int) -> dict:
            node = {
                "name": current_path.name or str(current_path),
                "path": str(current_path),
                "type": "dir" if current_path.is_dir() else "file",
            }

            if current_path.is_dir() and not current_path.is_symlink() and depth < max_depth:
                try:
                    children = []
                    for item in sorted(current_path.iterdir()):
                        if not include_hidden and item.name.startswith("."):
                            continue
                        if item.name in IGNORE_DIRS or is_ignored(item):
                            continue
                        if item.is_symlink() or not path_stays_inside(base_root, item):
                            continue
                        children.append(build_tree(item, depth + 1))
                    node["children"] = children
                except PermissionError:
                    node["error"] = "Permission denied"

            return node

        return [build_tree(base_path, 0)]

    def find_large_files(
        self,
        path: str,
        min_lines: int = 500,
        min_size_kb: int = 100,
        file_types: list[str] | None = None,
        root: str | None = None,
    ) -> list[FileInfo]:
        """Find files inside the workspace exceeding size or line count thresholds."""
        large_files = []
        base_root = self._root_for_call(root)
        base_path = resolve_within_root(base_root, path, allow_root=True)

        if not base_path.exists() or not base_path.is_dir():
            logger.warning(f"Invalid directory: {path}")
            return large_files

        if file_types is None:
            file_types = sorted(FS_TEXT_EXTS)

        for file_path in walk_tree(base_path, include_hidden=True):
            if not file_path.is_file():
                continue
            if file_path.suffix not in file_types:
                continue
            if is_ignored(file_path) or not path_stays_inside(base_root, file_path):
                continue

            try:
                stat = file_path.stat()
                size_kb = stat.st_size / 1024

                if size_kb >= min_size_kb:
                    lines = read_text_lines(file_path)
                    line_count = len(lines) if lines is not None else 0

                    if line_count >= min_lines:
                        large_files.append(FileInfo(
                            path=str(file_path),
                            size=stat.st_size,
                            modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            is_dir=False,
                            extension=file_path.suffix,
                            line_count=line_count,
                        ))

            except (PermissionError, OSError) as e:
                logger.debug(f"Skipping {file_path}: {e}")
                continue

        large_files.sort(key=lambda f: f.size, reverse=True)
        return large_files

    # ── Agent Interface ───────────────────────────────────────────────────────

    def run_task(self, project: Project, task_description: str) -> AgentResult:
        """
        Execute a filesystem task inside the project sandbox.

        Supported operations:
        - "scan <path>" - Scan directory
        - "search <path> <query>" - Search in files
        - "tree <path>" - List directory tree
        - "large <path>" - Find large files
        - "info <path>" - Get file info

        This is the path Supervisor uses, including tasks started from Telegram.
        """
        parts = task_description.strip().split()

        if len(parts) < 2:
            return self._make_result(
                project=project,
                task=task_description,
                success=False,
                summary="Invalid task format. Use: <operation> <path> [options]",
            )

        operation = parts[0].lower()
        target_path = parts[1]

        try:
            root = self.effective_root(project)
            resolved = resolve_within_root(root, target_path, allow_root=True)
        except UnsafePathError as e:
            logger.warning(f"Rejected filesystem path {target_path!r}: {e}")
            return self._make_result(
                project=project,
                task=task_description,
                success=False,
                summary=str(e),
            )

        if not resolved.exists():
            return self._make_result(
                project=project,
                task=task_description,
                success=False,
                summary=f"Path does not exist: {target_path}",
            )

        try:
            if operation == "scan":
                pattern = parts[2] if len(parts) > 2 else None
                result = self.scan_directory(target_path, pattern, root=root)
                return self._make_result(
                    project=project,
                    task=task_description,
                    success=True,
                    summary=f"Scanned {result.total_files} files, {result.total_dirs} directories",
                    details={
                        "path": result.path,
                        "total_files": result.total_files,
                        "total_dirs": result.total_dirs,
                        "total_size_bytes": result.total_size,
                        "files": [f.path for f in result.files[:100]],
                    },
                )

            elif operation == "search":
                if len(parts) < 3:
                    return self._make_result(
                        project=project,
                        task=task_description,
                        success=False,
                        summary="Search requires a query pattern",
                    )
                query = parts[2]
                result = self.search_files(target_path, query, root=root)
                return self._make_result(
                    project=project,
                    task=task_description,
                    success=True,
                    summary=f"Found {result.total_matches} matches in {result.files_matched} files",
                    details={
                        "path": result.path,
                        "query": query,
                        "files_matched": result.files_matched,
                        "total_matches": result.total_matches,
                        "matches": result.matches[:10],
                    },
                )

            elif operation == "tree":
                max_depth = int(parts[2]) if len(parts) > 2 else 3
                tree = self.list_tree(target_path, max_depth, root=root)
                return self._make_result(
                    project=project,
                    task=task_description,
                    success=True,
                    summary=f"Generated tree structure (depth={max_depth})",
                    details={
                        "path": target_path,
                        "tree": tree,
                    },
                )

            elif operation == "large":
                min_lines = int(parts[2]) if len(parts) > 2 else 500
                large_files = self.find_large_files(target_path, min_lines=min_lines, root=root)
                return self._make_result(
                    project=project,
                    task=task_description,
                    success=True,
                    summary=f"Found {len(large_files)} large files (>{min_lines} lines)",
                    details={
                        "path": target_path,
                        "min_lines": min_lines,
                        "files": [
                            {"path": f.path, "lines": f.line_count, "size": f.size}
                            for f in large_files[:20]
                        ],
                    },
                )

            elif operation == "info":
                info = self.get_file_info(target_path, root=root)
                if info:
                    return self._make_result(
                        project=project,
                        task=task_description,
                        success=True,
                        summary=f"File info retrieved: {Path(target_path).name}",
                        details={
                            "path": info.path,
                            "size": info.size,
                            "modified": info.modified,
                            "is_dir": info.is_dir,
                            "extension": info.extension,
                            "line_count": info.line_count,
                        },
                    )
                else:
                    return self._make_result(
                        project=project,
                        task=task_description,
                        success=False,
                        summary=f"Could not get info for: {target_path}",
                    )

            else:
                return self._make_result(
                    project=project,
                    task=task_description,
                    success=False,
                    summary=f"Unknown operation: {operation}",
                )

        except UnsafePathError as e:
            logger.warning(f"Rejected filesystem path {target_path!r}: {e}")
            return self._make_result(
                project=project,
                task=task_description,
                success=False,
                summary=str(e),
            )
        except Exception as e:
            logger.exception(f"FilesystemAgent error: {e}")
            return self._make_result(
                project=project,
                task=task_description,
                success=False,
                summary=f"Error: {str(e)}",
            )
