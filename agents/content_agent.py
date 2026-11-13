"""
agents/content_agent.py — Generates documentation, changelogs, README
updates, and inline docstrings for projects.
"""
from __future__ import annotations

import logging
from pathlib import Path

from agents.base import BaseAgent, AgentResult
from config.loader import Project, Settings
from tools.fs_stats import read_text_lines, walk_tree
from tools.llm_json import parse_llm_json
from tools.run_cmd import run_cmd
from tools.safe_paths import UnsafePathError, safe_join

logger = logging.getLogger(__name__)


CONTENT_SYSTEM_PROMPT = """
You are ContentAgent, a technical writer and documentation expert.
Given project info and recent git changes, generate high-quality content.
Output as JSON: {
  "type": "readme|changelog|docstring|api_docs|migration_guide",
  "filename": "<relative path>",
  "content": "<full markdown or code content>",
  "summary": "<one-line description of what was generated>"
}
Write clear, professional, developer-friendly documentation.
Use proper Markdown with headers, code blocks, and examples.
"""

DOCSTRING_SYSTEM_PROMPT = """
You are ContentAgent generating Python/JS/TS docstrings.
Given source code, return enriched code with complete docstrings added.
Preserve all existing logic exactly — only add/improve documentation.
Output ONLY the updated source code, no explanations.
"""


class ContentAgent(BaseAgent):
    """Generates docs, changelogs, READMEs, and docstrings."""

    name = "content"

    # ── Git helpers ───────────────────────────────────────────────────────

    def _git_log(self, path: str, count: int = 20) -> str:
        result = run_cmd(
            ["git", "log", f"-{count}", "--oneline", "--no-decorate"],
            cwd=path,
            timeout=10,
        )
        if result.error or result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _git_diff(self, path: str) -> str:
        """Get diff of recent changes for changelog generation."""
        result = run_cmd(
            ["git", "diff", "HEAD~5..HEAD", "--stat"],
            cwd=path,
            timeout=15,
        )
        if result.error or result.returncode != 0:
            return ""
        return result.stdout.strip()[:3000]

    def _read_existing_readme(self, path: str) -> str:
        for name in ("README.md", "readme.md", "README.rst"):
            f = Path(path) / name
            if f.exists():
                return f.read_text(errors="ignore")[:4000]
        return ""

    def _collect_source_files(self, path: str, language: str, max_files: int = 5) -> list[dict]:
        """Sample source files for docstring generation."""
        ext_map = {
            "python": ".py",
            "javascript": ".js",
            "typescript": ".ts",
        }
        ext = ext_map.get(language, ".py")
        root = Path(path)
        if not root.is_dir():
            return []

        files = []
        # Same walk as monitor and filesystem scans: ignored directories are
        # not entered, and symlinks are not followed or read.
        for f in walk_tree(root):
            if not f.is_file() or f.suffix != ext:
                continue
            lines = read_text_lines(f)
            if lines is None or len(lines) >= 300:
                continue
            files.append({
                "path": str(f.relative_to(root)),
                "content": "\n".join(lines)[:3000],
            })
            if len(files) >= max_files:
                break

        return files

    # ── Content generation methods ────────────────────────────────────────

    def _generate_readme(self, project: Project) -> tuple[str, str]:
        existing = self._read_existing_readme(project.path)
        git_log = self._git_log(project.path)

        messages = [{
            "role": "user",
            "content": (
                f"Project: {project.name} ({project.language})\n"
                f"Repo: {project.repo}\n"
                f"Labels: {', '.join(project.labels)}\n\n"
                f"Existing README (if any):\n{existing or '(none)'}\n\n"
                f"Recent commits:\n{git_log or '(none)'}\n\n"
                "Generate a comprehensive README.md for this project."
            ),
        }]
        return self._call_llm(messages, system=CONTENT_SYSTEM_PROMPT), "README.md"

    def _generate_changelog(self, project: Project) -> tuple[str, str]:
        git_log = self._git_log(project.path, count=50)
        diff_stat = self._git_diff(project.path)

        messages = [{
            "role": "user",
            "content": (
                f"Project: {project.name}\n\n"
                f"Recent commits:\n{git_log}\n\n"
                f"Diff stats:\n{diff_stat}\n\n"
                "Generate a CHANGELOG.md entry for the latest changes. "
                "Use Keep a Changelog format."
            ),
        }]
        return self._call_llm(messages, system=CONTENT_SYSTEM_PROMPT), "CHANGELOG.md"

    def _generate_docstrings(self, project: Project) -> list[dict]:
        source_files = self._collect_source_files(project.path, project.language)
        results = []

        for src in source_files:
            messages = [{
                "role": "user",
                "content": (
                    f"File: {src['path']}\n\n"
                    f"```{project.language}\n{src['content']}\n```\n\n"
                    "Add comprehensive docstrings to all functions and classes."
                ),
            }]
            enriched = self._call_llm(messages, system=DOCSTRING_SYSTEM_PROMPT)
            results.append({"file": src["path"], "content": enriched})

        return results

    # ── Main task ─────────────────────────────────────────────────────────

    def run_task(self, project: Project, task_description: str = "") -> AgentResult:
        logger.info(f"[ContentAgent] Generating docs for: {project.id}")
        self.notify(f"📝 Content generation started: {project.name}")

        if not project.path:
            return self._make_result(project, "content", False, "No local path configured")

        # Determine what to generate from task description
        task_lower = (task_description or "").lower()
        artifacts: list[str] = []
        details: dict = {}

        if "readme" in task_lower or not task_description:
            raw, filename = self._generate_readme(project)
            details["readme"] = self._parse_content_response(raw, filename)
            artifacts.append(filename)

        if "changelog" in task_lower or not task_description:
            raw, filename = self._generate_changelog(project)
            details["changelog"] = self._parse_content_response(raw, filename)
            artifacts.append(filename)

        if "docstring" in task_lower or "docs" in task_lower:
            doc_results = self._generate_docstrings(project)
            details["docstrings"] = doc_results
            artifacts.extend([d["file"] for d in doc_results])

        # A notification plus a skipped write is not a successful content task.
        if self.settings.workspace.approval_required and artifacts:
            self.notify(
                "⚠️ Approval required — "
                f"{len(artifacts)} artifact(s) for {project.name} not written."
            )
            summary = f"Generated {len(artifacts)} artifact(s). Awaiting approval."
            details["status"] = "awaiting_approval"
            details["skipped_for_approval"] = True
            self.notify(f"⏸ Content awaiting approval: {project.name} — {summary}")
            return self._make_result(
                project=project,
                task="content",
                success=False,
                summary=summary,
                details=details,
                artifacts=artifacts,
            )

        written = self._write_content_files(project, details)
        summary = f"Generated {len(artifacts)} artifact(s). {len(written)} written to disk."
        details["status"] = "ok"
        details["skipped_for_approval"] = False
        details["written"] = written

        self.notify(f"✅ Content done: {project.name} — {summary}")

        return self._make_result(
            project=project,
            task="content",
            success=True,
            summary=summary,
            details=details,
            artifacts=artifacts,
        )

    def _parse_content_response(self, raw: str, fallback_filename: str) -> dict:
        parsed = parse_llm_json(raw)
        if parsed is None:
            return {"filename": fallback_filename, "content": raw, "raw": True}
        return parsed

    def _write_content_files(self, project: Project, details: dict) -> list[str]:
        written = []
        root = Path(project.path)
        for key, item in details.items():
            if isinstance(item, dict) and "content" in item and "filename" in item:
                try:
                    target = safe_join(root, str(item["filename"]))
                except UnsafePathError as e:
                    logger.warning(f"Rejected unsafe filename {item['filename']!r}: {e}")
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(item["content"])
                    written.append(item["filename"])
                    logger.info(f"Wrote {target}")
                except Exception as e:
                    logger.warning(f"Failed to write {target}: {e}")
        return written
