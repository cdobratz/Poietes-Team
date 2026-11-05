"""Shared subprocess runner and filesystem statistics keep caller-specific results."""
from __future__ import annotations

from pathlib import Path

from agents.filesystem_agent import FilesystemAgent
from agents.monitor_agent import MonitorAgent
from agents.security_agent import SecurityAgent
from config.loader import (
    AgentConfig, LLMBackend, LLMConfig, SecurityToolsConfig, Settings, WorkspaceConfig,
)
from memory.mem0_client import InMemoryFallback
from tools.fs_stats import IGNORE_DIRS, read_text_lines, scan_project_stats
from tools.run_cmd import run_cmd


def _settings() -> Settings:
    return Settings(
        llm=LLMConfig(
            default="c",
            backends={"c": LLMBackend(provider="anthropic", model="m", api_key="k")},
        ),
        agents={n: AgentConfig(llm="c", max_iterations=1)
                for n in ("monitor", "coder", "security", "content", "filesystem")},
        workspace=WorkspaceConfig(approval_required=False, sandbox_writes=False),
        security=SecurityToolsConfig(bandit=False, semgrep=False, safety=False),
    )


def test_monitor_and_security_command_results(tmp_path: Path):
    settings = _settings()
    monitor = MonitorAgent(settings, InMemoryFallback())
    security = SecurityAgent(settings, InMemoryFallback())

    rc, out, err = monitor._run_cmd(
        ["python3", "-c", "import sys; sys.stdout.write('o'); sys.stderr.write('e')"],
        str(tmp_path),
    )
    assert (rc, out, err) == (0, "o", "e")

    rc, out, err = monitor._run_cmd(["no-such-binary-poietes"], str(tmp_path))
    assert rc == 1 and out == "" and err == "Command not found: no-such-binary-poietes"

    rc, combined = security._run(["no-such-binary-poietes"], str(tmp_path))
    assert rc == 127 and combined == "not found: no-such-binary-poietes"

    timed = run_cmd(["python3", "-c", "import time; time.sleep(5)"], str(tmp_path), timeout=0.2)
    assert timed.error == "timeout"


def test_shared_ignore_and_line_count(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: one\nprint(1)\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.py").write_text("x = 1\n")

    stats = scan_project_stats(str(tmp_path))
    assert stats["todo_count"] == 1
    assert stats["total_files"] == 1
    assert "node_modules" in IGNORE_DIRS

    root = str(tmp_path)
    settings = _settings()
    settings.workspace.root = root
    scanned = FilesystemAgent(settings, InMemoryFallback()).scan_directory(".")
    names = [Path(f.path).name for f in scanned.files]
    assert "a.py" in names
    assert "pkg.py" not in names

    assert read_text_lines(tmp_path / "src") is None
    info = FilesystemAgent(settings, InMemoryFallback()).get_file_info("src/a.py")
    assert info is not None and info.line_count == 2
