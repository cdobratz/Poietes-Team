"""Path containment: safe_join and its use in the coder/content agents and Serena shim."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agents.coder_agent import CoderAgent
from agents.content_agent import ContentAgent
from config.loader import (
    AgentConfig, LLMBackend, LLMConfig, Project, SecurityToolsConfig, Settings, WorkspaceConfig,
)
from mcp_servers.serena_mcp import LocalSerenaShim
from memory.mem0_client import InMemoryFallback
from tools.safe_paths import UnsafePathError, resolve_within_root, safe_join


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "project"
    r.mkdir()
    return r


def test_safe_join_allows_nested(root: Path):
    assert safe_join(root, "src/app.py") == (root / "src/app.py").resolve()


@pytest.mark.parametrize("bad", ["../evil.py", "a/../../evil.py", "/etc/passwd", "", "a\0b", "."])
def test_safe_join_rejects(root: Path, bad: str):
    with pytest.raises(UnsafePathError):
        safe_join(root, bad)


def test_safe_join_rejects_symlink_escape(root: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / "link")
    with pytest.raises(UnsafePathError):
        safe_join(root, "link/evil.py")


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


def test_coder_agent_rejects_traversal_and_absolute(root: Path, tmp_path: Path):
    agent = CoderAgent(_settings(), InMemoryFallback())
    abs_target = tmp_path / "abs.txt"
    ops = [
        {"op": "create", "file": "../escaped.txt", "content": "x"},
        {"op": "create", "file": str(abs_target), "content": "x"},
        {"op": "create", "file": "ok/inside.txt", "content": "y"},
    ]
    applied, failures = agent._apply_operations(ops, _project(root))
    assert len(applied) == 1 and "ok/inside.txt" in applied[0]
    assert len(failures) == 2
    assert not (tmp_path / "escaped.txt").exists()
    assert not abs_target.exists()
    assert (root / "ok/inside.txt").read_text() == "y"


def test_content_agent_rejects_traversal_and_absolute(root: Path, tmp_path: Path):
    agent = ContentAgent(_settings(), InMemoryFallback())
    abs_target = tmp_path / "abs.md"
    details = {
        "a": {"filename": "../escaped.md", "content": "x"},
        "b": {"filename": str(abs_target), "content": "x"},
        "c": {"filename": "docs/ok.md", "content": "y"},
    }
    written = agent._write_content_files(_project(root), details)
    assert written == ["docs/ok.md"]
    assert not (tmp_path / "escaped.md").exists()
    assert not abs_target.exists()


def test_serena_shim_apply_edit_rejects_escape(root: Path, tmp_path: Path):
    shim = LocalSerenaShim()
    for bad in ("../escaped.txt", str(tmp_path / "abs.txt")):
        res = shim.apply_edit({"op": "create", "file": bad, "content": "x"}, str(root))
        assert "error" in res
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "abs.txt").exists()
    ok = shim.apply_edit({"op": "create", "file": "a/b.txt", "content": "x"}, str(root))
    assert ok.get("success")


def test_resolve_within_root_allows_root_and_contained_absolute(root: Path):
    assert resolve_within_root(root, ".", allow_root=True) == root.resolve()
    nested = root / "src" / "app.py"
    assert resolve_within_root(root, nested) == nested.resolve()
    assert resolve_within_root(root, "src/app.py") == nested.resolve()


@pytest.mark.parametrize("bad", ["../evil.py", "a/../../evil.py", "", "a\0b"])
def test_resolve_within_root_rejects_escapes(root: Path, bad: str, tmp_path: Path):
    with pytest.raises(UnsafePathError):
        resolve_within_root(root, bad, allow_root=True)
    with pytest.raises(UnsafePathError):
        resolve_within_root(root, tmp_path / "outside.txt")


def test_resolve_within_root_rejects_symlink_escape(root: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / "link")
    with pytest.raises(UnsafePathError):
        resolve_within_root(root, "link/evil.py")


def test_resolve_within_root_requires_a_root(root: Path):
    with pytest.raises(UnsafePathError):
        resolve_within_root("", "a.txt")
    with pytest.raises(UnsafePathError):
        resolve_within_root(root, ".", allow_root=False)
