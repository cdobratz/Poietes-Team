"""
mcp_servers/serena_mcp.py: lightweight local fallback when the Serena server is not installed.

In production, run the real Serena server (pip install serena).
This shim handles local fallback when Serena is not installed,
using the shared project walk and Python AST. It does not start a subprocess.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tools.fs_stats import read_text_lines, walk_tree
from tools.safe_paths import UnsafePathError, safe_join


class LocalSerenaShim:
    """
    Fallback code intelligence when real Serena MCP is unavailable.
    Uses the shared project walk and Python AST for basic search.
    """

    def search_code(self, query: str, project_path: str, max_results: int = 5) -> list[dict]:
        """Search for code matching a query string.

        Uses the shared project walk. Ignored directories are not entered,
        symlinks are not read, and this method does not start a subprocess.
        """
        root = Path(project_path)
        if not query or not root.is_dir():
            return []

        needle = query.lower()
        matches: list[dict] = []
        for item in walk_tree(root):
            if not item.is_file():
                continue
            lines = read_text_lines(item)
            if not lines:
                continue
            rel = str(item.relative_to(root))
            for line_no, line in enumerate(lines, 1):
                if needle not in line.lower():
                    continue
                matches.append({
                    "file": rel,
                    "line": line_no,
                    "content": line.strip(),
                    "symbol": "",
                })
                if len(matches) >= max_results:
                    return matches
        return matches

    def get_symbol(self, name: str, project_path: str) -> dict:
        """Find a class or function definition inside the project walk."""
        root = Path(project_path)
        if not name or not root.is_dir():
            return {}
        for py_file in walk_tree(root):
            if not py_file.is_file() or py_file.suffix != ".py":
                continue
            lines = read_text_lines(py_file)
            if not lines:
                continue
            try:
                tree = ast.parse("\n".join(lines))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if node.name != name:
                    continue
                end = node.end_lineno or node.lineno
                return {
                    "name": name,
                    "file": str(py_file.relative_to(root)),
                    "line": node.lineno,
                    "content": "\n".join(lines[node.lineno - 1:end]),
                }
        return {}

    def list_symbols(self, file_path: str) -> list[dict]:
        """List all top-level symbols in a file."""
        try:
            source = Path(file_path).read_text(errors="ignore")
            tree = ast.parse(source)
            return [
                {
                    "name": node.name,
                    "type": type(node).__name__,
                    "line": node.lineno,
                }
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
        except Exception:
            return []

    def apply_edit(self, operation: dict, project_path: str) -> dict:
        """Apply a create, replace, insert, or delete edit inside ``project_path``."""
        op = operation.get("op", "")
        file_rel = operation.get("file", "")
        content = operation.get("content", "")
        search_target = operation.get("target", "")
        try:
            target = safe_join(project_path, file_rel)
        except UnsafePathError as e:
            return {"error": f"Unsafe path rejected: {e}"}

        if op == "create":
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            except OSError as e:
                return {"error": f"Create failed for {file_rel}: {e}"}
            return {"success": True, "file": file_rel}

        if op not in {"replace", "insert", "delete"}:
            return {"error": f"Unsupported op: {op}"}

        if not target.is_file():
            return {"error": f"File not found: {file_rel}"}

        try:
            old_content = target.read_text()
        except (OSError, UnicodeDecodeError) as e:
            return {"error": f"Cannot read {file_rel}: {e}"}

        if op == "replace":
            if not search_target or search_target not in old_content:
                return {"error": f"Target not found in {file_rel}"}
            new_content = old_content.replace(search_target, content, 1)
        elif op == "insert":
            if search_target:
                if search_target not in old_content:
                    return {"error": f"Target not found in {file_rel}"}
                idx = old_content.find(search_target) + len(search_target)
                new_content = old_content[:idx] + content + old_content[idx:]
            else:
                new_content = old_content + content
        else:
            needle = search_target or content
            if not needle or needle not in old_content:
                return {"error": f"Delete target not found in {file_rel}"}
            new_content = old_content.replace(needle, "", 1)

        try:
            target.write_text(new_content)
        except OSError as e:
            return {"error": f"Write failed for {file_rel}: {e}"}
        return {"success": True, "file": file_rel}
