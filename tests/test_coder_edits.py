"""Local edits when Serena MCP is disabled, and failed edits must not look successful."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.coder_agent import CoderAgent
from config.loader import (
    AgentConfig, LLMBackend, LLMConfig, Project, SecurityToolsConfig, Settings, WorkspaceConfig,
)
from memory.mem0_client import InMemoryFallback


def _settings() -> Settings:
    return Settings(
        llm=LLMConfig(
            default="c",
            backends={"c": LLMBackend(provider="anthropic", model="m", api_key="k")},
        ),
        agents={n: AgentConfig(llm="c", max_iterations=1)
                for n in ("monitor", "coder", "security", "content")},
        workspace=WorkspaceConfig(approval_required=False, sandbox_writes=False),
        security=SecurityToolsConfig(bandit=False, semgrep=False, safety=False),
    )


def _project(root: Path) -> Project:
    return Project(id="p", name="P", path=str(root))


def test_disabled_mcp_create_replace_insert_delete(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("alpha\nbeta\n")
    agent = CoderAgent(_settings(), InMemoryFallback())
    assert agent._serena is None

    applied, failures = agent._apply_operations([
        {"op": "create", "file": "new.txt", "content": "created", "description": "add file"},
        {"op": "replace", "file": "a.py", "target": "alpha", "content": "ALPHA"},
        {"op": "insert", "file": "a.py", "target": "beta", "content": "\ninserted"},
        {"op": "delete", "file": "a.py", "target": "ALPHA\n"},
    ], _project(root))

    assert failures == []
    assert len(applied) == 4
    assert (root / "new.txt").read_text() == "created"
    text = (root / "a.py").read_text()
    assert "ALPHA" not in text
    assert "beta" in text
    assert "inserted" in text


def test_disabled_mcp_failures_are_not_success(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("alpha\n")
    agent = CoderAgent(_settings(), InMemoryFallback())
    payload = json.dumps({
        "plan": "bad edits",
        "operations": [
            {"op": "create", "file": "ok.txt", "content": "yes"},
            {"op": "replace", "file": "missing.py", "target": "x", "content": "y"},
            {"op": "insert", "file": "a.py", "target": "nope", "content": "z"},
            {"op": "delete", "file": "a.py", "target": "missing-text"},
            {"op": "rename", "file": "a.py", "target": "alpha", "content": "nope"},
        ],
    })
    with patch.object(agent, "_call_llm", return_value=payload):
        result = agent.run_task(_project(root), "edit")

    assert result.success is False
    assert result.details["status"] == "failed"
    assert (root / "ok.txt").read_text() == "yes"
    assert (root / "a.py").read_text() == "alpha\n"
    assert len(result.details["failures"]) == 4
    assert len(result.details["applied"]) == 1


def test_no_applied_operation_is_not_success(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("alpha\n")
    agent = CoderAgent(_settings(), InMemoryFallback())
    payload = json.dumps({
        "plan": "nothing lands",
        "operations": [
            {"op": "replace", "file": "a.py", "target": "absent", "content": "x"},
            {"op": "delete", "file": "nope.py", "target": "x"},
        ],
    })
    with patch.object(agent, "_call_llm", return_value=payload):
        result = agent.run_task(_project(root), "edit")
    assert result.success is False
    assert result.details["applied"] == []
    assert (root / "a.py").read_text() == "alpha\n"


def test_enabled_serena_does_not_fall_back_to_local_create(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    agent = CoderAgent(_settings(), InMemoryFallback())

    class DownSerena:
        def apply_edit(self, operation, project_path):
            return {"error": "mcp down"}

    agent._serena = DownSerena()
    applied, failures = agent._apply_operations(
        [{"op": "create", "file": "x.txt", "content": "nope"}],
        _project(root),
    )
    assert applied == []
    assert failures
    assert not (root / "x.txt").exists()


def test_fenced_llm_json_still_applies(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("alpha\n")
    agent = CoderAgent(_settings(), InMemoryFallback())
    raw = "```json\n" + json.dumps({
        "plan": "replace alpha",
        "operations": [{
            "op": "replace", "file": "a.py", "target": "alpha", "content": "beta",
        }],
    }) + "\n```"
    with patch.object(agent, "_call_llm", return_value=raw):
        result = agent.run_task(_project(root), "edit")
    assert result.success is True
    assert (root / "a.py").read_text() == "beta\n"
