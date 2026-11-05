"""Filesystem paths stay inside the workspace, including supervisor/Telegram tasks."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.filesystem_agent import FilesystemAgent
from config.loader import (
    AgentConfig, LLMBackend, LLMConfig, Project, SecurityToolsConfig, Settings, WorkspaceConfig,
)
from memory.mem0_client import InMemoryFallback
from tools.safe_paths import UnsafePathError


def _settings(root: str = "") -> Settings:
    return Settings(
        llm=LLMConfig(
            default="c",
            backends={"c": LLMBackend(provider="anthropic", model="m", api_key="k")},
        ),
        agents={n: AgentConfig(llm="c", max_iterations=1)
                for n in ("monitor", "coder", "security", "content", "filesystem")},
        workspace=WorkspaceConfig(approval_required=False, sandbox_writes=False, root=root),
        security=SecurityToolsConfig(bandit=False, semgrep=False, safety=False),
    )


def _agent(root: str = "") -> FilesystemAgent:
    return FilesystemAgent(_settings(root), InMemoryFallback())


def test_scan_requires_workspace_root(tmp_path: Path):
    with pytest.raises(UnsafePathError):
        _agent().scan_directory(str(tmp_path))


def test_scan_search_tree_reject_escape_and_allow_inside(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOP-SECRET-DATA")
    (root / "keep.txt").write_text("hello TODO\n")
    link = root / "link"
    link.symlink_to(outside)

    agent = _agent(str(root))
    scanned = agent.scan_directory(".")
    names = [Path(f.path).name for f in scanned.files]
    assert "keep.txt" in names
    assert "secret.txt" not in names
    assert "link" not in names
    assert all("TOP-SECRET-DATA" not in f.path for f in scanned.files)

    with pytest.raises(UnsafePathError):
        agent.scan_directory("../outside")
    with pytest.raises(UnsafePathError):
        agent.scan_directory(str(secret))
    with pytest.raises(UnsafePathError):
        agent.scan_directory(".", pattern="../**/*")
    with pytest.raises(UnsafePathError):
        agent.search_files(".", "TODO", file_pattern="../**/*")

    found = agent.search_files(".", "TODO")
    assert found.total_matches == 1
    assert "secret.txt" not in str(found.matches)

    tree = agent.list_tree(".", max_depth=3)
    dumped = str(tree)
    assert "keep.txt" in dumped
    assert "secret.txt" not in dumped
    assert "TOP-SECRET-DATA" not in dumped

    info = agent.get_file_info("keep.txt")
    assert info is not None and info.line_count == 1
    with pytest.raises(UnsafePathError):
        agent.get_file_info(str(secret))


def test_telegram_supervisor_filesystem_task_stays_in_project(tmp_path: Path):
    """Supervisor.run_task is how a Telegram /run plan reaches FilesystemAgent."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "ok.txt").write_text("inside\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-DATA")
    # workspace.root unset: the project path is the sandbox (Telegram has no CLI root).
    agent = _agent("")
    project = Project(id="p", name="P", path=str(project_root))

    escaped = agent.run_task(project, f"scan {secret}")
    assert escaped.success is False
    assert "TOP-SECRET-DATA" not in escaped.summary
    assert "TOP-SECRET-DATA" not in str(escaped.details)

    dotdot = agent.run_task(project, "info ../secret.txt")
    assert dotdot.success is False
    assert "TOP-SECRET-DATA" not in dotdot.summary

    ok = agent.run_task(project, "scan .")
    assert ok.success is True
    assert ok.details["total_files"] >= 1

    # A configured workspace.root is an outer bound: the project must sit inside it,
    # and a sibling path is still rejected.
    parent = _agent(str(tmp_path))
    sibling = parent.run_task(project, f"search {tmp_path} TOP-SECRET")
    assert sibling.success is False
    assert "TOP-SECRET-DATA" not in str(sibling.details)

    outsider = Project(id="out", name="Out", path=str(tmp_path / "other"))
    (tmp_path / "other").mkdir()
    blocked = _agent(str(project_root)).run_task(outsider, "scan .")
    assert blocked.success is False
    assert "outside" in blocked.summary


def test_cli_fs_commands_are_guarded():
    text = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    for name in ("def fs_scan", "def fs_search", "def fs_tree", "def fs_large", "def fs_info"):
        start = text.index(name)
        chunk = text[start:start + 600]
        assert "_guard_fs" in chunk
        assert "_filesystem_agent" in chunk
