"""
agents/security_agent.py — Runs Bandit, Semgrep, and Safety scans,
then uses an LLM to triage and prioritise findings.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from agents.base import BaseAgent, AgentResult
from config.loader import Project, Settings

logger = logging.getLogger(__name__)


SECURITY_SYSTEM_PROMPT = """
You are SecurityAgent, an application security expert (OWASP, CWE, CVSS).
Given raw scan output from security tools, produce a structured audit report as JSON:
{
  "risk_level": "critical" | "high" | "medium" | "low" | "info",
  "findings": [
    {
      "id": "...",
      "severity": "critical|high|medium|low",
      "title": "...",
      "file": "...",
      "line": 0,
      "description": "...",
      "remediation": "..."
    }
  ],
  "dependency_vulns": [...],
  "summary": "...",
  "immediate_actions": [...]
}
"""


class SecurityAgent(BaseAgent):
    """Audits projects using Bandit (Python), Semgrep, and pip-audit/npm audit."""

    name = "security"

    def __init__(self, settings: Settings, memory=None, messenger=None):
        super().__init__(settings, memory, messenger)
        self._cfg = settings.security

    def _run(self, cmd: list[str], cwd: str) -> tuple[int, str]:
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
            return r.returncode, r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return 1, "TIMEOUT"
        except FileNotFoundError:
            return 127, f"not found: {cmd[0]}"
        except Exception as e:
            return 1, str(e)

    # ── Tool runners ──────────────────────────────────────────────────────

    def _run_bandit(self, path: str) -> dict:
        if not self._cfg.bandit:
            return {}
        rc, out = self._run(
            ["bandit", "-r", path, "-f", "json", "-q"],
            cwd=path,
        )
        if rc == 127:
            return {"tool": "bandit", "error": "not installed"}
        try:
            data = json.loads(out)
            issues = data.get("results", [])
            return {
                "tool": "bandit",
                "total": len(issues),
                "issues": [
                    {
                        "severity": i.get("issue_severity", ""),
                        "confidence": i.get("issue_confidence", ""),
                        "text": i.get("issue_text", ""),
                        "file": i.get("filename", "").replace(path, ""),
                        "line": i.get("line_number", 0),
                        "test_id": i.get("test_id", ""),
                    }
                    for i in issues
                ],
            }
        except json.JSONDecodeError:
            return {"tool": "bandit", "raw": out[:2000]}

    def _run_semgrep(self, path: str, language: str) -> dict:
        if not self._cfg.semgrep:
            return {}
        lang_map = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "go": "go",
            "java": "java",
        }
        lang = lang_map.get(language, "auto")
        rc, out = self._run(
            ["semgrep", "--config", f"p/owasp-top-ten", "--json", "--lang", lang, path],
            cwd=path,
        )
        if rc == 127:
            return {"tool": "semgrep", "error": "not installed"}
        try:
            data = json.loads(out)
            results = data.get("results", [])
            return {
                "tool": "semgrep",
                "total": len(results),
                "findings": [
                    {
                        "rule": r.get("check_id", ""),
                        "message": r.get("extra", {}).get("message", ""),
                        "file": r.get("path", "").replace(path, ""),
                        "line": r.get("start", {}).get("line", 0),
                        "severity": r.get("extra", {}).get("severity", ""),
                    }
                    for r in results[:20]
                ],
            }
        except json.JSONDecodeError:
            return {"tool": "semgrep", "raw": out[:2000]}

    def _run_dependency_audit(self, path: str, language: str) -> dict:
        if not self._cfg.safety:
            return {}
        if language == "python":
            rc, out = self._run(["pip-audit", "--format", "json"], cwd=path)
            if rc == 127:
                # fallback to safety
                rc, out = self._run(["safety", "check", "--json"], cwd=path)
        elif language in ("javascript", "typescript"):
            rc, out = self._run(["npm", "audit", "--json"], cwd=path)
        else:
            return {"tool": "dependency_audit", "skipped": language}

        try:
            return {"tool": "dependency_audit", "raw": json.loads(out)}
        except json.JSONDecodeError:
            return {"tool": "dependency_audit", "output": out[:2000]}

    # ── Main task ─────────────────────────────────────────────────────────

    def run_task(self, project: Project, task_description: str = "") -> AgentResult:
        logger.info(f"[SecurityAgent] Auditing: {project.id}")
        self.notify(f"🔒 Security scan started: {project.name}")

        if not project.path:
            return self._make_result(project, "security", False, "No local path configured")

        bandit = _json_truncate(self._run_bandit(project.path))
        semgrep = _json_truncate(self._run_semgrep(project.path, project.language))
        deps = _json_truncate(self._run_dependency_audit(project.path, project.language))

        scan_data = {
            "project": project.id,
            "language": project.language,
            "bandit": bandit,
            "semgrep": semgrep,
            "dependencies": deps,
        }

        prior = self.recall(f"security audit {project.id}", project.id)

        messages = [
            {
                "role": "user",
                "content": (
                    f"Security scan data:\n```json\n{json.dumps(scan_data, indent=2)}\n```"
                    + (f"\n\nPrevious audit notes:\n{prior}" if prior else "")
                ),
            }
        ]

        raw = self._call_llm(messages, system=SECURITY_SYSTEM_PROMPT)

        try:
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            report = json.loads(clean)
        except (json.JSONDecodeError, AttributeError):
            report = {"raw": raw, "risk_level": "unknown"}

        risk = report.get("risk_level", "unknown")
        findings_count = len(report.get("findings", []))
        summary = f"Risk: {risk.upper()}. {findings_count} finding(s) identified."

        # Alert on critical/high
        if risk in ("critical", "high"):
            self.notify(f"🚨 {risk.upper()} security issues in {project.name}: {summary}")

        self.remember(
            key=f"security:{project.id}",
            value=json.dumps({"risk": risk, "count": findings_count}),
            project_id=project.id,
        )

        return self._make_result(
            project=project,
            task="security",
            success=True,
            summary=summary,
            details={"report": report, "raw_scans": scan_data},
        )


def _json_truncate(data: dict, max_items: int = 20) -> dict:
    """Truncate list fields to avoid token overflow."""
    if not data:
        return data
    for k, v in data.items():
        if isinstance(v, list) and len(v) > max_items:
            data[k] = v[:max_items] + [{"truncated": f"... {len(v) - max_items} more"}]
    return data
