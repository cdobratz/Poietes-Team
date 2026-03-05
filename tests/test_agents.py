"""
tests/test_agents.py — Unit tests for all agents.
Uses mock LLM responses to test without real API calls.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.loader import (
    Project, ProjectTasks, Settings, LLMConfig, LLMBackend,
    MCPConfig, MCPServer, MessagingConfig, GitConfig, WorkspaceConfig,
    SecurityToolsConfig, AgentConfig
)
from agents.monitor_agent import MonitorAgent
from agents.coder_agent import CoderAgent
from agents.security_agent import SecurityAgent
from agents.content_agent import ContentAgent
from memory.mem0_client import InMemoryFallback


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        llm=LLMConfig(
            default="claude",
            backends={
                "claude": LLMBackend(
                    provider="anthropic",
                    model="claude-sonnet-4-20250514",
                    api_key="test-key",
                )
            },
        ),
        agents={
            "monitor": AgentConfig(llm="claude", max_iterations=5),
            "coder": AgentConfig(llm="claude", max_iterations=5),
            "security": AgentConfig(llm="claude", max_iterations=5),
            "content": AgentConfig(llm="claude", max_iterations=5),
        },
        workspace=WorkspaceConfig(approval_required=False, sandbox_writes=False),
        security=SecurityToolsConfig(bandit=False, semgrep=False, safety=False),
    )


@pytest.fixture
def mock_memory():
    return InMemoryFallback()


@pytest.fixture
def sample_project(tmp_path: Path) -> Project:
    """Create a real temporary project directory with Python files."""
    # Create some Python files
    (tmp_path / "main.py").write_text(
        "import os\n\ndef hello():\n    # TODO: improve this\n    return 'hello'\n"
    )
    (tmp_path / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )
    # Init git
    os.system(f"git -C {tmp_path} init -q")
    os.system(f"git -C {tmp_path} add . && git -C {tmp_path} commit -m 'init' -q --allow-empty-message 2>/dev/null || true")

    return Project(
        id="test-project",
        name="Test Project",
        path=str(tmp_path),
        repo="github.com/test/test-project",
        language="python",
        enabled=True,
        tasks=ProjectTasks(monitor=True, coder=True, security=True, content=True),
    )


LLM_MONITOR_RESPONSE = json.dumps({
    "health_score": 75,
    "critical": [],
    "warnings": ["High TODO density"],
    "suggestions": ["Reduce file complexity"],
    "next_steps": ["Run security scan"],
})

LLM_CODER_RESPONSE = json.dumps({
    "plan": "Add a subtract function to utils.py",
    "operations": [
        {
            "op": "replace",
            "file": "utils.py",
            "target": "def add(a, b):\n    return a + b",
            "content": "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b",
            "description": "Add subtract function",
        }
    ],
})

LLM_SECURITY_RESPONSE = json.dumps({
    "risk_level": "low",
    "findings": [],
    "dependency_vulns": [],
    "summary": "No critical issues found",
    "immediate_actions": [],
})

LLM_CONTENT_RESPONSE = json.dumps({
    "type": "readme",
    "filename": "README.md",
    "content": "# Test Project\n\nA test project.",
    "summary": "Generated README",
})


# ─── MonitorAgent Tests ───────────────────────────────────────────────────────

class TestMonitorAgent:

    def test_scan_file_stats(self, mock_settings, mock_memory, sample_project):
        agent = MonitorAgent(mock_settings, mock_memory)
        stats = agent._scan_file_stats(sample_project.path)
        assert stats["total_files"] >= 2
        assert stats["todo_count"] >= 1

    def test_run_task_success(self, mock_settings, mock_memory, sample_project):
        agent = MonitorAgent(mock_settings, mock_memory)
        with patch.object(agent, "_call_llm", return_value=LLM_MONITOR_RESPONSE):
            result = agent.run_task(sample_project, "check health")
        assert result.success
        assert "75" in result.summary
        assert result.agent_name == "monitor"

    def test_run_task_no_path(self, mock_settings, mock_memory):
        agent = MonitorAgent(mock_settings, mock_memory)
        project = Project(id="no-path", name="No Path", language="python")
        result = agent.run_task(project)
        assert not result.success

    def test_memory_storage(self, mock_settings, mock_memory, sample_project):
        agent = MonitorAgent(mock_settings, mock_memory)
        with patch.object(agent, "_call_llm", return_value=LLM_MONITOR_RESPONSE):
            agent.run_task(sample_project)
        memories = mock_memory.get_all(user_id="agent:monitor")
        assert len(memories) > 0


# ─── CoderAgent Tests ─────────────────────────────────────────────────────────

class TestCoderAgent:

    def test_run_task_dry_run(self, mock_settings, mock_memory, sample_project):
        # With approval_required=True, no files written
        mock_settings.workspace.approval_required = True
        agent = CoderAgent(mock_settings, mock_memory)
        with patch.object(agent, "_call_llm", return_value=LLM_CODER_RESPONSE):
            result = agent.run_task(sample_project, "add subtract function")
        assert result.success
        assert result.details["skipped_for_approval"] is True

    def test_run_task_applies_ops(self, mock_settings, mock_memory, sample_project):
        mock_settings.workspace.approval_required = False
        agent = CoderAgent(mock_settings, mock_memory)
        with patch.object(agent, "_call_llm", return_value=LLM_CODER_RESPONSE):
            result = agent.run_task(sample_project, "add subtract function")
        assert result.success
        assert len(result.details["operations"]) > 0

    def test_no_serena_graceful(self, mock_settings, mock_memory, sample_project):
        """Ensure CoderAgent works without Serena MCP."""
        mock_settings.mcp.serena.enabled = False
        agent = CoderAgent(mock_settings, mock_memory)
        assert agent._serena is None
        ctx = agent._gather_context("test", sample_project)
        assert "unavailable" in ctx.lower()


# ─── SecurityAgent Tests ──────────────────────────────────────────────────────

class TestSecurityAgent:

    def test_run_task(self, mock_settings, mock_memory, sample_project):
        agent = SecurityAgent(mock_settings, mock_memory)
        with patch.object(agent, "_call_llm", return_value=LLM_SECURITY_RESPONSE):
            result = agent.run_task(sample_project)
        assert result.success
        assert "low" in result.summary.lower()

    def test_bandit_disabled(self, mock_settings, mock_memory, sample_project):
        mock_settings.security.bandit = False
        agent = SecurityAgent(mock_settings, mock_memory)
        result = agent._run_bandit(sample_project.path)
        assert result == {}


# ─── ContentAgent Tests ───────────────────────────────────────────────────────

class TestContentAgent:

    def test_generate_readme(self, mock_settings, mock_memory, sample_project):
        mock_settings.workspace.approval_required = False
        agent = ContentAgent(mock_settings, mock_memory)
        with patch.object(agent, "_call_llm", return_value=LLM_CONTENT_RESPONSE):
            result = agent.run_task(sample_project, "generate readme")
        assert result.success
        assert "README.md" in result.artifacts

    def test_collect_source_files(self, mock_settings, mock_memory, sample_project):
        agent = ContentAgent(mock_settings, mock_memory)
        files = agent._collect_source_files(sample_project.path, "python")
        assert len(files) >= 1
        assert any("main.py" in f["path"] or "utils.py" in f["path"] for f in files)


# ─── Memory Tests ─────────────────────────────────────────────────────────────

class TestInMemoryFallback:

    def test_add_and_search(self):
        mem = InMemoryFallback()
        mem.add([{"role": "user", "content": "project health is good"}], user_id="agent:monitor")
        results = mem.search("health", user_id="agent:monitor")
        assert len(results["results"]) > 0

    def test_user_isolation(self):
        mem = InMemoryFallback()
        mem.add([{"role": "user", "content": "secret data"}], user_id="agent:monitor")
        results = mem.search("secret", user_id="agent:coder")
        assert len(results["results"]) == 0
