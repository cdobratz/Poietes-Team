"""
agents/coder_agent.py — AI-driven feature development using Serena MCP
for semantic code retrieval and targeted edits.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from agents.base import BaseAgent, AgentResult
from config.loader import Project, Settings
from mcp_servers.serena_mcp import LocalSerenaShim
from tools.llm_json import parse_llm_json
from tools.safe_paths import UnsafePathError, safe_join

logger = logging.getLogger(__name__)


CODER_SYSTEM_PROMPT = """
You are CoderAgent, an expert software engineer.
Given a task and relevant code context (provided by Serena), produce:
1. A step-by-step implementation plan
2. Precise file edits as a JSON array of operations

Each operation must follow this schema:
{
  "op": "replace" | "insert" | "delete" | "create",
  "file": "<relative path>",
  "target": "<function/class/line to modify>",   // for replace/delete
  "content": "<new code>",                        // for replace/insert/create
  "description": "<why>"
}

Always preserve existing style, imports, and patterns.
Output ONLY valid JSON as: {"plan": "...", "operations": [...]}
"""


class SerenaClient:
    """
    Thin HTTP client wrapping the Serena MCP server.
    Provides semantic code search and targeted edits.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30)

    def _call(self, tool: str, params: dict) -> dict:
        """Make a JSON-RPC-style MCP tool call."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": params},
        }
        try:
            resp = self._client.post(f"{self.base_url}/mcp", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {})
        except httpx.HTTPError as e:
            logger.warning(f"Serena MCP call failed ({tool}): {e}")
            return {"error": str(e)}

    def search_code(self, query: str, project_path: str, max_results: int = 5) -> list[dict]:
        result = self._call("search_code", {
            "query": query,
            "project_path": project_path,
            "max_results": max_results,
        })
        return result.get("matches", [])

    def get_symbol(self, name: str, project_path: str) -> dict:
        return self._call("get_symbol", {"name": name, "project_path": project_path})

    def apply_edit(self, operation: dict, project_path: str) -> dict:
        return self._call("apply_edit", {**operation, "project_path": project_path})

    def list_symbols(self, file_path: str) -> list[dict]:
        return self._call("list_symbols", {"file_path": file_path}).get("symbols", [])


class CoderAgent(BaseAgent):
    """Implements features and fixes using Serena MCP for semantic code edits."""

    name = "coder"

    def __init__(self, settings: Settings, memory=None, messenger=None):
        super().__init__(settings, memory, messenger)
        serena_cfg = settings.mcp.serena
        self._serena: SerenaClient | None = None
        if serena_cfg.enabled:
            self._serena = SerenaClient(serena_cfg.url)
            logger.info("Serena MCP client initialised")
        else:
            logger.info("Serena MCP disabled — using raw file edits")

    # ── Serena context gathering ──────────────────────────────────────────

    def _gather_context(self, task: str, project: Project) -> str:
        """Use Serena to retrieve semantically relevant code snippets."""
        if not self._serena or not project.path:
            return "(Serena unavailable — no code context)"

        matches = self._serena.search_code(task, project.path, max_results=6)
        if not matches:
            return "(No relevant code found via Serena)"

        lines = ["Relevant code context from Serena:"]
        for m in matches:
            lines.append(f"\n### {m.get('file', '?')} — {m.get('symbol', '')}")
            lines.append(f"```{project.language}")
            lines.append(m.get("content", "").strip())
            lines.append("```")
        return "\n".join(lines)

    # ── Edit application ──────────────────────────────────────────────────

    def _editor(self) -> Any:
        """Serena MCP when it is enabled, otherwise the local edit shim."""
        if self._serena is not None:
            return self._serena
        return LocalSerenaShim()

    def _apply_operations(
        self, operations: list[dict], project: Project
    ) -> tuple[list[str], list[str]]:
        """Apply every operation through one editor.

        Returns ``(applied, failures)``. An operation that is unsafe, unsupported,
        or rejected by the editor is a failure. Nothing is reported as applied
        unless the editor accepted it. There is no create-only fallback.
        """
        applied: list[str] = []
        failures: list[str] = []
        editor = self._editor()

        for op in operations:
            if not isinstance(op, dict):
                failures.append("invalid operation (expected an object)")
                continue
            op_name = str(op.get("op", ""))
            file_rel = str(op.get("file", ""))
            desc = op.get("description", op_name or "edit")
            label = f"{op_name or 'edit'}: {file_rel} — {desc}"

            if not project.path:
                failures.append(f"{label}: no project path configured")
                continue
            try:
                safe_join(project.path, file_rel)
            except UnsafePathError as e:
                logger.warning(f"Rejected unsafe edit target {file_rel!r}: {e}")
                failures.append(f"{label}: {e}")
                continue

            if not hasattr(editor, "apply_edit"):
                failures.append(f"{label}: editor does not support apply_edit")
                continue

            result = editor.apply_edit(op, project.path)
            if not isinstance(result, dict) or "error" in result or result.get("success") is False:
                err = result.get("error") if isinstance(result, dict) else "edit failed"
                logger.warning(f"Edit failed ({op_name} {file_rel}): {err}")
                failures.append(f"{label}: {err}")
                continue

            applied.append(label)
            logger.info(f"Applied {op_name} on {file_rel}")

        return applied, failures

    # ── Main task ─────────────────────────────────────────────────────────

    def run_task(self, project: Project, task_description: str) -> AgentResult:
        logger.info(f"[CoderAgent] Task: {task_description[:80]} on {project.id}")
        self.notify(f"⚙️ Coding task started: {project.name}")

        prior = self.recall(f"recent changes {project.id}", project.id)
        context = self._gather_context(task_description, project)

        messages = [
            {
                "role": "user",
                "content": (
                    f"Project: {project.name} ({project.language})\n"
                    f"Task: {task_description}\n\n"
                    f"{context}"
                    + (f"\n\nRecent changes:\n{prior}" if prior else "")
                ),
            }
        ]

        raw = self._call_llm(messages, system=CODER_SYSTEM_PROMPT)

        response = parse_llm_json(raw) or {"plan": raw, "operations": []}

        plan = response.get("plan", "")
        operations = response.get("operations", [])
        if not isinstance(operations, list):
            operations = []

        # Check approval gate. Notifying and then skipping is not a successful edit.
        failures: list[str] = []
        if self.settings.workspace.approval_required and operations:
            self.notify(
                f"⚠️ Approval required — {len(operations)} edit(s) planned for {project.name}.\n"
                f"Plan: {plan[:200]}"
            )
            logger.warning("Approval required but running non-interactively — skipping writes")
            applied: list[str] = []
            skipped = True
            success = False
            status = "awaiting_approval"
        else:
            applied, failures = self._apply_operations(operations, project)
            skipped = False
            success = not (operations and len(applied) != len(operations))
            status = "ok" if success else "failed"

        summary = (
            f"{'Awaiting approval. ' if skipped else ''}"
            f"{len(applied)}/{len(operations)} operation(s) applied."
        )
        if failures:
            summary += f" {len(failures)} failed."

        # Persist plan to memory
        self.remember(
            key=f"coder:{project.id}:{task_description[:40]}",
            value=json.dumps({"plan": plan, "ops": len(operations)}),
            project_id=project.id,
        )

        if skipped:
            self.notify(f"⏸ Awaiting approval: {project.name} — {summary}")
        elif success:
            self.notify(f"✅ Coder done: {project.name} — {summary}")
        else:
            self.notify(f"❌ Coder failed: {project.name} — {summary}")

        return self._make_result(
            project=project,
            task="coder",
            success=success,
            summary=summary,
            details={
                "plan": plan,
                "operations": operations,
                "applied": applied,
                "failures": failures,
                "skipped_for_approval": skipped,
                "status": status,
            },
            artifacts=applied,
        )
