"""
mcp_servers/serena_mcp.py — Lightweight Serena MCP server shim.

In production, run the real Serena server (pip install serena).
This shim handles local fallback when Serena is not installed,
using basic AST analysis and grep for code search.
"""
from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalSerenaShim:
    """
    Fallback code intelligence when real Serena MCP is unavailable.
    Uses grep + Python AST for basic semantic search.
    """

    def search_code(self, query: str, project_path: str, max_results: int = 5) -> list[dict]:
        """Search for code matching a query string."""
        matches = []
        root = Path(project_path)
        if not root.exists():
            return []

        # Use ripgrep if available, else grep
        for cmd in [
            ["rg", "--json", "-i", query, str(root)],
            ["grep", "-r", "-n", "-i", "--include=*.py", query, str(root)],
        ]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    lines = r.stdout.strip().splitlines()[:max_results * 3]
                    for line in lines:
                        try:
                            data = json.loads(line)  # ripgrep JSON
                            if data.get("type") == "match":
                                m = data["data"]
                                matches.append({
                                    "file": m["path"]["text"].replace(project_path, ""),
                                    "line": m["line_number"],
                                    "content": m["lines"]["text"].strip(),
                                    "symbol": "",
                                })
                        except (json.JSONDecodeError, KeyError):
                            # grep format: file:line:content
                            parts = line.split(":", 2)
                            if len(parts) >= 3:
                                matches.append({
                                    "file": parts[0].replace(project_path, ""),
                                    "line": parts[1],
                                    "content": parts[2].strip(),
                                    "symbol": "",
                                })
                        if len(matches) >= max_results:
                            break
                    break
            except FileNotFoundError:
                continue

        return matches[:max_results]

    def get_symbol(self, name: str, project_path: str) -> dict:
        """Find a class or function definition."""
        root = Path(project_path)
        for py_file in root.rglob("*.py"):
            try:
                source = py_file.read_text(errors="ignore")
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name == name:
                            lines = source.splitlines()
                            snippet = "\n".join(lines[node.lineno - 1:node.end_lineno])
                            return {
                                "name": name,
                                "file": str(py_file.relative_to(root)),
                                "line": node.lineno,
                                "content": snippet,
                            }
            except (SyntaxError, Exception):
                continue
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
        """Apply a code edit operation."""
        op = operation.get("op", "")
        file_rel = operation.get("file", "")
        content = operation.get("content", "")
        target = Path(project_path) / file_rel

        if op == "create":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            return {"success": True, "file": file_rel}

        if op == "replace" and target.exists():
            old_content = target.read_text()
            search_target = operation.get("target", "")
            if search_target and search_target in old_content:
                new_content = old_content.replace(search_target, content, 1)
                target.write_text(new_content)
                return {"success": True, "file": file_rel}
            return {"error": f"Target not found in {file_rel}"}

        return {"error": f"Unsupported op: {op}"}
