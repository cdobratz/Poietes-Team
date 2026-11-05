"""
agents/monitor_agent.py — Scans projects for code issues, dead code,
drift, outdated deps, large files, and TODO density.
"""
from __future__ import annotations

import json
import logging

from agents.base import BaseAgent, AgentResult
from config.loader import Project, Settings
from tools.fs_stats import scan_project_stats
from tools.llm_json import parse_llm_json
from tools.run_cmd import run_cmd

logger = logging.getLogger(__name__)


MONITOR_SYSTEM_PROMPT = """
You are MonitorAgent, an expert code health analyst.
Given a scan report of a software project, produce a concise health summary.
Identify: critical issues, warnings, code smells, dead code hints, and
actionable next steps. Output as JSON with keys:
  health_score (0-100), critical [], warnings [], suggestions [], next_steps []
"""


class MonitorAgent(BaseAgent):
    """Scans a project codebase and reports health metrics."""

    name = "monitor"

    def __init__(self, settings: Settings, memory=None, messenger=None):
        super().__init__(settings, memory, messenger)

    # ── Scanning helpers ──────────────────────────────────────────────────

    def _run_cmd(self, cmd: list[str], cwd: str) -> tuple[int, str, str]:
        """Run a subprocess command, return (returncode, stdout, stderr)."""
        result = run_cmd(cmd, cwd, timeout=120)
        if result.error == "timeout":
            return 1, "", "Command timed out"
        if result.error == "not_found":
            return 1, "", f"Command not found: {cmd[0]}"
        if result.error:
            return 1, "", result.error_detail
        return result.returncode, result.stdout, result.stderr

    def _scan_file_stats(self, path: str) -> dict:
        """Count files, lines, TODOs, large files."""
        return scan_project_stats(path)

    def _scan_git_status(self, path: str) -> dict:
        """Check for uncommitted changes and stale branches."""
        rc, out, err = self._run_cmd(["git", "status", "--porcelain"], path)
        uncommitted = [l for l in out.splitlines() if l.strip()] if rc == 0 else []

        rc2, log_out, _ = self._run_cmd(
            ["git", "log", "--oneline", "-10"], path
        )
        recent_commits = log_out.strip().splitlines() if rc2 == 0 else []

        return {
            "uncommitted_changes": len(uncommitted),
            "uncommitted_files": uncommitted[:10],
            "recent_commits": recent_commits,
        }

    def _scan_dependencies(self, path: str, language: str) -> dict:
        """Check for outdated/vulnerable dependencies."""
        results: dict = {"outdated": [], "vulnerable": []}

        if language == "python":
            rc, out, _ = self._run_cmd(["pip", "list", "--outdated", "--format=json"], path)
            if rc == 0:
                try:
                    outdated = json.loads(out)
                    results["outdated"] = [f"{p['name']} ({p['version']} → {p['latest_version']})" for p in outdated[:10]]
                except json.JSONDecodeError:
                    pass

        elif language in ("javascript", "typescript"):
            rc, out, _ = self._run_cmd(["npm", "outdated", "--json"], path)
            if out:
                try:
                    data = json.loads(out)
                    results["outdated"] = list(data.keys())[:10]
                except json.JSONDecodeError:
                    pass

        return results

    # ── Main task ─────────────────────────────────────────────────────────

    def run_task(self, project: Project, task_description: str = "") -> AgentResult:
        logger.info(f"[MonitorAgent] Scanning project: {project.id}")
        self.notify(f"🔍 Starting scan: {project.name}")

        if not project.path:
            return self._make_result(
                project, "monitor", False,
                "No local path configured — skipping file scan",
            )

        # Gather raw scan data
        file_stats = self._scan_file_stats(project.path)
        git_stats = self._scan_git_status(project.path)
        dep_stats = self._scan_dependencies(project.path, project.language)

        raw_report = {
            "project": project.id,
            "language": project.language,
            "file_stats": file_stats,
            "git_status": git_stats,
            "dependencies": dep_stats,
            "task_context": task_description,
        }

        # Recall any previous scan context from memory
        prior_memory = self.recall(f"previous scan {project.id}", project.id)

        messages = [
            {
                "role": "user",
                "content": (
                    f"Project scan report:\n```json\n{json.dumps(raw_report, indent=2)}\n```"
                    + (f"\n\nPrevious context:\n{prior_memory}" if prior_memory else "")
                ),
            }
        ]

        analysis_raw = self._call_llm(messages, system=MONITOR_SYSTEM_PROMPT)

        analysis = parse_llm_json(analysis_raw) or {"raw": analysis_raw, "health_score": 50}

        health = analysis.get("health_score", 50)
        criticals = analysis.get("critical", [])
        summary = f"Health score: {health}/100. {len(criticals)} critical issue(s)."

        # Persist scan summary to memory
        self.remember(
            key=f"scan:{project.id}",
            value=json.dumps(analysis),
            project_id=project.id,
        )

        self.notify(f"✅ Scan complete: {project.name} — {summary}")

        return self._make_result(
            project=project,
            task="monitor",
            success=True,
            summary=summary,
            details={
                "analysis": analysis,
                "raw_stats": raw_report,
            },
        )
