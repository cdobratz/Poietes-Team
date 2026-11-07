"""Warp trial: execution-free dry-run, saved workflows, JSON, and cancellation."""
from __future__ import annotations

import ast
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import yaml

from config.loader import (
    ConfigError,
    Project,
    ProjectRegistry,
    ProjectTasks,
    Settings,
    WorkspaceConfig,
    load_projects,
    load_settings,
)
from tools.offline_plan import cancelled_payload, results_payload, run_dry_run

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "config" / "warp-trial"
PLAN_WORKFLOW = ROOT / ".warp" / "workflows" / "poietes-plan.yaml"
RUN_WORKFLOW = ROOT / ".warp" / "workflows" / "poietes-run.yaml"


def _settings() -> Settings:
    return Settings(workspace=WorkspaceConfig(approval_required=True))


def _registry(*projects: Project) -> ProjectRegistry:
    return ProjectRegistry(projects=list(projects))


def _project(project_id: str, **tasks: bool) -> Project:
    flags = {"monitor": True, "coder": False, "security": False, "content": False}
    flags.update(tasks)
    return Project(
        id=project_id,
        name=project_id,
        enabled=True,
        tasks=ProjectTasks(**flags),
    )


def _guard_side_effects(monkeypatch):
    """Fail the test if the dry-run path writes, spawns a process, or connects."""
    real_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        flags = mode if isinstance(mode, str) else "r"
        if any(flag in flags for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"unexpected write: {file} mode={flags}")
        return real_open(file, mode, *args, **kwargs)

    def no_connect(self, address):
        raise AssertionError(f"unexpected connect to {address}")

    def no_subprocess(*args, **kwargs):
        raise AssertionError(f"unexpected subprocess: {args!r}")

    monkeypatch.setattr("builtins.open", tracking_open)
    monkeypatch.setattr(socket.socket, "connect", no_connect)
    monkeypatch.setattr(subprocess, "run", no_subprocess)

    import memory.mem0_client as mem

    def no_memory(*args, **kwargs):
        raise AssertionError("dry-run constructed remote memory")

    monkeypatch.setattr(mem, "build_memory_client", no_memory)


def test_dry_run_success_does_not_execute(monkeypatch):
    monkeypatch.setenv("POIETES_CONFIG_DIR", str(FIXTURE))
    _guard_side_effects(monkeypatch)
    before = threading.active_count()
    code, payload = run_dry_run(
        task="list configured agents",
        project_ids="warp-fixture",
        output=None,
        load_settings=load_settings,
        load_projects=load_projects,
    )
    assert code == 0
    assert payload["ok"] is True
    assert payload["status"] == "planned"
    assert payload["dry_run"] is True
    assert payload["execution"] == "none"
    assert payload["approval_required"] is True
    assert payload["projects"] == ["warp-fixture"]
    assert payload["plan"][0]["agents"] == ["monitor"]
    assert payload["plan"][0]["executes"] is False
    assert "filesystem" not in payload["plan"][0]["agents"]
    assert threading.active_count() == before


def test_dry_run_errors_still_do_not_execute(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("POIETES_CONFIG_DIR", str(FIXTURE))
    _guard_side_effects(monkeypatch)
    code, payload = run_dry_run(
        task="list configured agents",
        project_ids="missing-project",
        output=None,
        load_settings=load_settings,
        load_projects=load_projects,
    )
    assert code == 1
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["execution"] == "none"
    assert "missing-project" in payload["error"]

    output = tmp_path / "plan.json"
    code, payload = run_dry_run(
        task="list configured agents",
        project_ids="warp-fixture",
        output=str(output),
        load_settings=load_settings,
        load_projects=load_projects,
    )
    assert code == 2
    assert payload["status"] == "unsupported"
    assert not output.exists()

    code, payload = run_dry_run(
        task="   ",
        project_ids="warp-fixture",
        output=None,
        load_settings=load_settings,
        load_projects=load_projects,
    )
    assert code == 2
    assert "empty" in payload["error"]

    def broken_settings():
        raise RuntimeError("boom")

    code, payload = run_dry_run(
        task="list configured agents",
        project_ids="warp-fixture",
        output=None,
        load_settings=broken_settings,
        load_projects=broken_settings,
    )
    assert code == 1
    assert payload["execution"] == "none"
    assert "boom" in payload["error"]


def test_dry_run_cancel_starts_nothing():
    def explode():
        raise KeyboardInterrupt()

    code, payload = run_dry_run(
        task="list configured agents",
        project_ids="warp-fixture",
        output=None,
        load_settings=explode,
        load_projects=explode,
    )
    assert code == 130
    assert payload["status"] == "cancelled"
    assert payload["execution"] == "none"
    assert payload == cancelled_payload(dry_run=True, task="list configured agents")


def test_unsupported_project_with_no_agents():
    project = _project("empty", monitor=False)
    code, payload = run_dry_run(
        task="do something",
        project_ids="empty",
        output=None,
        load_settings=_settings,
        load_projects=lambda: _registry(project),
    )
    assert code == 2
    assert payload["status"] == "unsupported"
    assert payload["execution"] == "none"


def test_isolated_fixture_disables_telegram_and_remote_memory(monkeypatch):
    monkeypatch.setenv("POIETES_CONFIG_DIR", str(FIXTURE))
    settings = load_settings()
    assert settings.messaging.telegram.enabled is False
    assert settings.messaging.telegram.bot_token == ""
    assert settings.mcp.mem0.enabled is False
    assert settings.mcp.mem0.api_key == ""
    assert settings.workspace.approval_required is True
    projects = load_projects()
    assert [project.id for project in projects.projects] == ["warp-fixture"]
    assert projects.projects[0].path == ""


def test_config_override_does_not_fall_back_or_change_the_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("POIETES_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="was not used"):
        load_settings()
    monkeypatch.delenv("POIETES_CONFIG_DIR", raising=False)
    settings = load_settings()
    assert settings.llm.default == "claude"


def test_live_json_success_error_and_cancel_payloads():
    code, body = results_payload(
        [{"success": True, "project": "warp-fixture", "agent": "monitor", "summary": "ok"}],
        task="list configured agents",
    )
    assert code == 0
    assert body["ok"] is True and body["status"] == "ok"
    assert body["dry_run"] is False and body["execution"] == "completed"

    code, body = results_payload(
        [{"success": False, "project": "warp-fixture", "summary": "failed"}],
        task="list configured agents",
    )
    assert code == 1
    assert body["ok"] is False and body["status"] == "error"

    cancelled = cancelled_payload(dry_run=False, task="list configured agents")
    assert cancelled["exit_code"] == 130
    assert cancelled["execution"] == "none"


def test_parallel_cancel_does_not_wait_on_daemon_workers(monkeypatch):
    from agents.supervisor_agent import SupervisorAgent

    supervisor = SupervisorAgent(_settings(), _registry())
    release = threading.Event()
    started = threading.Event()

    def slow(step, project):
        started.set()
        release.wait(5)
        return []

    supervisor._execute_step = slow  # type: ignore[method-assign]
    real_join = threading.Thread.join

    def raising_join(self, timeout=None):
        if self.name == "poietes-agent" and started.is_set():
            raise KeyboardInterrupt()
        return real_join(self, timeout)

    monkeypatch.setattr(threading.Thread, "join", raising_join)
    project = _project("p")
    steps = [
        {"project_id": "p", "agents": ["monitor"]},
        {"project_id": "p", "agents": ["monitor"]},
    ]
    began = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            supervisor._execute_parallel(steps, {"p": project})
        assert time.monotonic() - began < 1.5
        workers = [thread for thread in threading.enumerate() if thread.name == "poietes-agent"]
        assert workers
        assert all(thread.daemon for thread in workers)
    finally:
        release.set()
        for thread in threading.enumerate():
            if thread.name == "poietes-agent":
                real_join(thread, 2)


def _workflow(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _shell_commands(command: str) -> list[str]:
    commands = []
    for line in command.splitlines():
        for piece in line.split("&&"):
            piece = piece.strip()
            if piece and not piece.startswith("export "):
                commands.append(piece)
    return commands


def test_saved_workflows_match_documented_format_and_do_not_auto_run():
    plan = _workflow(PLAN_WORKFLOW)
    real = _workflow(RUN_WORKFLOW)
    for workflow in (plan, real):
        assert workflow["name"]
        assert workflow["command"]
        assert set(workflow["shells"]) <= {"bash", "zsh", "fish"}
        names = {item["name"] for item in workflow["arguments"]}
        used = set(re.findall(r"\{\{(\w+)\}\}", workflow["command"]))
        assert used == names
        by_name = {item["name"]: item for item in workflow["arguments"]}
        assert "default_value" not in by_name["project_id"]
        assert "default_value" not in by_name["task"]
        assert by_name["config_dir"]["default_value"] == "config/warp-trial"

    plan_commands = _shell_commands(plan["command"])
    assert plan_commands == [
        "python main.py validate",
        "python main.py list-projects",
        "python main.py run --dry-run --task {{task}} --projects {{project_id}}",
    ]
    assert "run --json" not in plan["command"]
    assert "poietes-run" not in plan["command"]

    assert _shell_commands(real["command"]) == [
        "python main.py run --json --task {{task}} --projects {{project_id}}",
    ]
    assert "--dry-run" not in real["command"]


def test_main_dry_run_returns_before_supervisor():
    source = (ROOT / "main.py").read_text()
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(getattr(body[0], "value", None), ast.Constant)
    ):
        body = body[1:]
    first = body[0]
    assert isinstance(first, ast.If)
    dumped = ast.dump(first)
    assert "run_dry_run" in dumped
    assert "_build_supervisor" not in dumped
    assert any(isinstance(node, ast.Raise) for node in ast.walk(first))
    rest = ast.dump(ast.Module(body=body[1:], type_ignores=[]))
    assert "_build_supervisor" in rest
    assert "cancelled_payload" in source
    assert "results_payload" in source
