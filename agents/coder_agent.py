"""
agents/coder_agent.py — AI-driven feature development using Serena MCP
for semantic code retrieval and targeted edits.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from agents.base import BaseAgent, AgentResult
from config.loader import Project, Settings

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

    def _apply_operations(self, operations: list[dict], project: Project) -> list[str]:
        """Apply code operations, using Serena if available, else direct file I/O."""
        applied: list[str] = []

        for op in operations:
            file_rel = op.get("file", "")
            desc = op.get("description", op.get("op", "edit"))

            if self._serena and project.path:
                result = self._serena.apply_edit(op, project.path)
                if "error" not in result:
                    applied.append(f"{op['op']}: {file_rel} — {desc}")
                    logger.info(f"Serena applied: {op['op']} on {file_rel}")
                    continue

            # Fallback: direct Python file ops for create/replace
            if project.path and op.get("op") == "create":
                target = Path(project.path) / file_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(op.get("content", ""))
                applied.append(f"create: {file_rel} — {desc}")

        return applied

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

        # Parse response
        try:
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            response = json.loads(clean)
        except (json.JSONDecodeError, AttributeError):
            response = {"plan": raw, "operations": []}

        plan = response.get("plan", "")
        operations = response.get("operations", [])

        # Check approval gate
        if self.settings.workspace.approval_required and operations:
            self.notify(
                f"⚠️ Approval required — {len(operations)} edit(s) planned for {project.name}.\n"
                f"Plan: {plan[:200]}"
            )
            logger.warning("Approval required but running non-interactively — skipping writes")
            applied: list[str] = []
            skipped = True
        else:
            applied = self._apply_operations(operations, project)
            skipped = False

        summary = (
            f"{'(Dry-run) ' if skipped else ''}{len(applied)}/{len(operations)} "
            f"operation(s) applied."
        )

        # Persist plan to memory
        self.remember(
            key=f"coder:{project.id}:{task_description[:40]}",
            value=json.dumps({"plan": plan, "ops": len(operations)}),
            project_id=project.id,
        )

        self.notify(f"✅ Coder done: {project.name} — {summary}")

        return self._make_result(
            project=project,
            task="coder",
            success=True,
            summary=summary,
            details={
                "plan": plan,
                "operations": operations,
                "applied": applied,
                "skipped_for_approval": skipped,
            },
            artifacts=applied,
        )
