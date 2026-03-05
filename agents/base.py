"""
agents/base.py — Base class all agents inherit from.

Wraps OpenHands SDK concepts (LLM, tool execution, event loop) into a clean
interface. Falls back to direct LiteLLM calls when openhands-ai is not
installed, so the project runs in "lite" mode for local testing.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from config.loader import Settings, Project

logger = logging.getLogger(__name__)

# ─── Try importing OpenHands; fall back to LiteLLM directly ──────────────────

try:
    from openhands.agent import Agent as _OHAgent          # type: ignore
    from openhands.tools import BashTool, FileEditorTool   # type: ignore
    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    logger.warning("openhands-ai not installed — running in LiteLLM-direct mode")

try:
    import litellm                                          # type: ignore
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False


# ─── Event / result types ─────────────────────────────────────────────────────

class AgentResult:
    """Typed result returned by every agent task."""

    def __init__(
        self,
        agent_name: str,
        project_id: str,
        task: str,
        success: bool,
        summary: str,
        details: dict[str, Any] | None = None,
        artifacts: list[str] | None = None,
    ):
        self.agent_name = agent_name
        self.project_id = project_id
        self.task = task
        self.success = success
        self.summary = summary
        self.details = details or {}
        self.artifacts = artifacts or []

    def to_dict(self) -> dict:
        return {
            "agent": self.agent_name,
            "project": self.project_id,
            "task": self.task,
            "success": self.success,
            "summary": self.summary,
            "details": self.details,
            "artifacts": self.artifacts,
        }

    def __repr__(self) -> str:
        status = "✅" if self.success else "❌"
        return f"{status} [{self.agent_name}] {self.project_id}: {self.summary}"


# ─── Base Agent ───────────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """
    All specialist agents extend this class.

    Subclasses implement:
      - `run_task(project, task_description)` → AgentResult
    """

    name: str = "base"

    def __init__(self, settings: Settings, memory=None, messenger=None):
        self.settings = settings
        self.memory = memory          # Mem0 client (optional)
        self.messenger = messenger    # Telegram/CLI messenger (optional)

        cfg = settings.get_agent_cfg(self.name)
        self.llm_backend = settings.get_llm_backend(cfg.llm)
        self.max_iterations = cfg.max_iterations

        self._tools: list[Any] = []
        self._setup_tools()

    # ── Tool registration ──────────────────────────────────────────────────

    def _setup_tools(self) -> None:
        """Override to register agent-specific tools."""
        pass

    def add_tool(self, tool: Any) -> None:
        self._tools.append(tool)

    # ── LLM call (OpenHands or LiteLLM fallback) ──────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call_llm(self, messages: list[dict], system: str = "") -> str:
        """Send messages to the configured LLM and return the text response."""
        b = self.llm_backend

        if LITELLM_AVAILABLE:
            model_str = f"{b.provider}/{b.model}" if b.provider else b.model
            kwargs: dict[str, Any] = {
                "model": model_str,
                "messages": messages,
            }
            if system:
                kwargs["messages"] = [{"role": "system", "content": system}] + messages
            if b.api_key:
                kwargs["api_key"] = b.api_key
            if b.base_url:
                kwargs["base_url"] = b.base_url

            response = litellm.completion(**kwargs)
            return response.choices[0].message.content or ""

        # Absolute fallback: return empty string and log warning
        logger.error("Neither openhands-ai nor litellm is available!")
        return ""

    # ── Memory helpers ─────────────────────────────────────────────────────

    def remember(self, key: str, value: str, project_id: str = "") -> None:
        if self.memory:
            try:
                self.memory.add(
                    messages=[{"role": "assistant", "content": value}],
                    user_id=f"agent:{self.name}",
                    metadata={"key": key, "project": project_id},
                )
            except Exception as e:
                logger.warning(f"Memory write failed: {e}")

    def recall(self, query: str, project_id: str = "") -> str:
        if not self.memory:
            return ""
        try:
            results = self.memory.search(
                query=query,
                user_id=f"agent:{self.name}",
                filters={"project": project_id} if project_id else {},
            )
            memories = [r["memory"] for r in results.get("results", [])]
            return "\n".join(memories)
        except Exception as e:
            logger.warning(f"Memory recall failed: {e}")
            return ""

    # ── Messaging helpers ──────────────────────────────────────────────────

    def notify(self, message: str) -> None:
        if self.messenger:
            self.messenger.send(f"[{self.name.upper()}] {message}")

    # ── Main interface ─────────────────────────────────────────────────────

    @abstractmethod
    def run_task(self, project: Project, task_description: str) -> AgentResult:
        """Execute a task on the given project. Must be implemented by subclasses."""
        ...

    def _make_result(
        self,
        project: Project,
        task: str,
        success: bool,
        summary: str,
        details: dict | None = None,
        artifacts: list[str] | None = None,
    ) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            project_id=project.id,
            task=task,
            success=success,
            summary=summary,
            details=details,
            artifacts=artifacts,
        )
