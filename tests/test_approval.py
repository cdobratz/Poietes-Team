"""Approval skips are not success, and LLM JSON parsing is shared."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.coder_agent import CoderAgent
from agents.content_agent import ContentAgent
from config.loader import (
    AgentConfig, LLMBackend, LLMConfig, Project, SecurityToolsConfig, Settings, WorkspaceConfig,
)
from memory.mem0_client import InMemoryFallback
from tools.llm_json import parse_llm_json


def _settings(*, approve: bool) -> Settings:
    return Settings(
        llm=LLMConfig(
            default="c",
            backends={"c": LLMBackend(provider="anthropic", model="m", api_key="k")},
        ),
        agents={n: AgentConfig(llm="c", max_iterations=1)
                for n in ("monitor", "coder", "security", "content")},
        workspace=WorkspaceConfig(approval_required=approve, sandbox_writes=False),
        security=SecurityToolsConfig(bandit=False, semgrep=False, safety=False),
    )


class _Box:
    def __init__(self):
        self.messages: list[str] = []

    def send(self, message: str) -> None:
        self.messages.append(message)


def test_coder_approval_notifies_then_does_not_succeed(tmp_path: Path):
    (tmp_path / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    box = _Box()
    agent = CoderAgent(_settings(approve=True), InMemoryFallback(), messenger=box)
    payload = json.dumps({
        "plan": "add subtract",
        "operations": [{
            "op": "replace",
            "file": "utils.py",
            "target": "def add(a, b):\n    return a + b",
            "content": "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b",
        }],
    })
    project = Project(id="p", name="P", path=str(tmp_path))
    with patch.object(agent, "_call_llm", return_value=payload):
        result = agent.run_task(project, "add subtract")

    assert result.success is False
    assert result.details["status"] == "awaiting_approval"
    assert result.details["skipped_for_approval"] is True
    assert result.details["applied"] == []
    assert "subtract" not in (tmp_path / "utils.py").read_text()
    joined = "\n".join(box.messages)
    assert "Approval required" in joined
    assert "✅" not in joined


def test_content_approval_notifies_then_does_not_write(tmp_path: Path):
    box = _Box()
    agent = ContentAgent(_settings(approve=True), InMemoryFallback(), messenger=box)
    project = Project(id="p", name="P", path=str(tmp_path), language="python")
    raw = json.dumps({
        "type": "readme",
        "filename": "README.md",
        "content": "# Secret write\n",
        "summary": "readme",
    })
    with patch.object(agent, "_call_llm", return_value=raw):
        result = agent.run_task(project, "generate readme")

    assert result.success is False
    assert result.details["status"] == "awaiting_approval"
    assert not (tmp_path / "README.md").exists()
    joined = "\n".join(box.messages)
    assert "Approval required" in joined
    assert "✅" not in joined


def test_parse_llm_json_fences_and_invalid():
    assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_llm_json('```\n{"a": 1}\n```') == {"a": 1}
    assert parse_llm_json("not json") is None
    assert parse_llm_json("[1, 2]") is None
    assert parse_llm_json(None) is None  # type: ignore[arg-type]
