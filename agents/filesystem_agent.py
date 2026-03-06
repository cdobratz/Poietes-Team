"""
agents/filesystem_agent.py — Agent for scanning and exploring arbitrary local directories.

Provides file operations including:
- Recursive directory scanning with glob patterns
- Content search (grep-like)
- File metadata (size, dates, type)
- Directory tree structure
- Large file detection
"""
from __future__ import annotations

import os
import re
import glob
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.base import AgentResult, BaseAgent
from config.loader import Project, Settings

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
    Agent for filesystem operations on arbitrary directories.
    Unlike MonitorAgent which works on configured projects,
    this agent accepts any directory path as input.
    """

    name = "filesystem"

    def __init__(self, settings: Settings, memory=None, messenger=None):
        super().__init__(settings, memory, messenger)

    # ── Core Operations ───────────────────────────────────────────────────────

    def scan_directory(
        self,
        path: str,
        pattern: str | None = None,
        include_hidden: bool = False,
    ) -> ScanResult:
        """
        Recursively scan a directory, optionally filtering by glob pattern.
        
        Args:
            path: Directory path to scan
            pattern: Optional glob pattern (e.g., "*.py", "**/*.ts")
            include_hidden: Whether to include hidden files/directories
            
        Returns:
            ScanResult with list of files and statistics
        """
        result = ScanResult(path=path)
        base_path = Path(path)
        
        if not base_path.exists():
            logger.warning(f"Path does not exist: {path}")
            return result
            
        if not base_path.is_dir():
            logger.warning(f"Path is not a directory: {path}")
            return result
        
        try:
            if pattern:
                # Use glob pattern
                matches = base_path.glob(pattern)
            else:
                # Recursive walk
                matches = base_path.rglob("*")
            
            for item in matches:
                # Skip hidden files if requested
                if not include_hidden and any(
                    part.startswith(".") for part in item.parts
                ):
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
                    
                    # Count lines for text files
                    if not is_dir and item.suffix in {".py", ".js", ".ts", ".txt", ".md", ".yaml", ".yml", ".json", ".sh"}:
                        try:
                            with open(item, "r", encoding="utf-8", errors="ignore") as f:
                                file_info.line_count = sum(1 for _ in f)
                        except:
                            pass
                    
                    result.files.append(file_info)
                    
                    if is_dir:
                        result.total_dirs += 1
                    else:
                        result.total_files += 1
                        result.total_size += stat.st_size
                        
                except (PermissionError, OSError) as e:
                    logger.debug(f"Skipping {item}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error scanning {path}: {e}")
            
        return result

    def search_files(
        self,
        path: str,
        query: str,
        file_pattern: str | None = None,
        case_sensitive: bool = False,
        include_context: int = 2,
    ) -> SearchResult:
        """
        Search for text content in files (grep-like).
        
        Args:
            path: Directory to search
            query: Search pattern (regex supported)
            file_pattern: Optional file filter (e.g., "*.py")
            case_sensitive: Whether search is case sensitive
            include_context: Lines of context around matches
            
        Returns:
            SearchResult with matches and statistics
        """
        result = SearchResult(path=path)
        base_path = Path(path)
        
        if not base_path.exists() or not base_path.is_dir():
            logger.warning(f"Invalid search path: {path}")
            return result
        
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(query, flags)
        except re.error as e:
            logger.error(f"Invalid regex pattern '{query}': {e}")
            return result
        
        # Get files to search
        if file_pattern:
            files_to_search = base_path.rglob(file_pattern)
        else:
            # Default to common text files
            files_to_search = []
            for ext in [".py", ".js", ".ts", ".txt", ".md", ".yaml", ".yml", ".json", ".sh", ".html", ".css"]:
                files_to_search.extend(base_path.rglob(f"*{ext}"))
        
        for file_path in files_to_search:
            if not file_path.is_file():
                continue
                
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
                    # Extract context around matches
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

    def get_file_info(self, path: str) -> FileInfo | None:
        """
        Get detailed metadata for a single file or directory.
        
        Args:
            path: File or directory path
            
        Returns:
            FileInfo object or None if path doesn't exist
        """
        p = Path(path)
        
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
            
            # Count lines for text files
            if not is_dir and p.suffix in {".py", ".js", ".ts", ".txt", ".md", ".yaml", ".yml", ".json", ".sh"}:
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        info.line_count = sum(1 for _ in f)
                except:
                    pass
                    
            return info
            
        except OSError as e:
            logger.error(f"Error getting info for {path}: {e}")
            return None

    def list_tree(
        self,
        path: str,
        max_depth: int = 3,
        include_hidden: bool = False,
    ) -> list[dict]:
        """
        Get directory tree structure as nested dictionaries.
        
        Args:
            path: Root directory path
            max_depth: Maximum depth to traverse
            include_hidden: Whether to include hidden files
            
        Returns:
            List of tree nodes (each node is a dict with name, type, children)
        """
        base_path = Path(path)
        
        if not base_path.exists() or not base_path.is_dir():
            logger.warning(f"Invalid directory: {path}")
            return []
        
        def build_tree(current_path: Path, depth: int) -> dict:
            node = {
                "name": current_path.name or str(current_path),
                "path": str(current_path),
                "type": "dir" if current_path.is_dir() else "file",
            }
            
            if current_path.is_dir() and depth < max_depth:
                try:
                    children = []
                    for item in sorted(current_path.iterdir()):
                        # Skip hidden if requested
                        if not include_hidden and item.name.startswith("."):
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
    ) -> list[FileInfo]:
        """
        Find files exceeding size or line count thresholds.
        
        Args:
            path: Directory to search
            min_lines: Minimum line count threshold
            min_size_kb: Minimum file size in KB
            file_types: Optional list of extensions to filter (e.g., [".py", ".js"])
            
        Returns:
            List of FileInfo objects for large files
        """
        large_files = []
        base_path = Path(path)
        
        if not base_path.exists() or not base_path.is_dir():
            logger.warning(f"Invalid directory: {path}")
            return large_files
        
        # Default file types if none specified
        if file_types is None:
            file_types = [".py", ".js", ".ts", ".txt", ".md", ".yaml", ".yml", ".json", ".sh"]
        
        for ext in file_types:
            for file_path in base_path.rglob(f"*{ext}"):
                if not file_path.is_file():
                    continue
                    
                try:
                    stat = file_path.stat()
                    size_kb = stat.st_size / 1024
                    
                    # Check size threshold
                    if size_kb >= min_size_kb:
                        # Count lines
                        line_count = 0
                        try:
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                line_count = sum(1 for _ in f)
                        except:
                            pass
                        
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
        
        # Sort by size descending
        large_files.sort(key=lambda f: f.size, reverse=True)
        return large_files

    # ── Agent Interface ───────────────────────────────────────────────────────

    def run_task(self, project: Project, task_description: str) -> AgentResult:
        """
        Execute a filesystem task.
        
        The task_description should contain the operation and path.
        Supported operations:
        - "scan <path>" - Scan directory
        - "search <path> <query>" - Search in files
        - "tree <path>" - List directory tree
        - "large <path>" - Find large files
        - "info <path>" - Get file info
        """
        # Parse the task description
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
        
        # Validate path exists
        if not Path(target_path).exists():
            return self._make_result(
                project=project,
                task=task_description,
                success=False,
                summary=f"Path does not exist: {target_path}",
            )
        
        try:
            if operation == "scan":
                pattern = parts[2] if len(parts) > 2 else None
                result = self.scan_directory(target_path, pattern)
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
                        "files": [f.path for f in result.files[:100]],  # Limit to 100 for output
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
                result = self.search_files(target_path, query)
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
                        "matches": result.matches[:10],  # Limit to 10 files
                    },
                )
            
            elif operation == "tree":
                max_depth = int(parts[2]) if len(parts) > 2 else 3
                tree = self.list_tree(target_path, max_depth)
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
                large_files = self.find_large_files(target_path, min_lines=min_lines)
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
                info = self.get_file_info(target_path)
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
                
        except Exception as e:
            logger.exception(f"FilesystemAgent error: {e}")
            return self._make_result(
                project=project,
                task=task_description,
                success=False,
                summary=f"Error: {str(e)}",
            )
