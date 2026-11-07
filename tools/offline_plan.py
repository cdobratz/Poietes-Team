"""
tools/offline_plan.py — Read-only plan for `run --dry-run`.

The plan is built from config that the caller already loaded. This module does
not construct agents, call an LLM, open a socket, start a worker, or write a file.
"""
from __future__ import annotations

from typing import Any, Callable

# Project task flags that a dry-run is allowed to list. Filesystem work is not
# one of them; a plan that needed it would have to execute.
_PLAN_AGENTS = ("monitor", "coder", "security", "content")


def _body(
    *,
    ok: bool,
    status: str,
    exit_code: int,
    dry_run: bool,
    execution: str,
    task: str,
    projects: list[str],
    plan: list[dict],
    error: str | None,
    approval_required: bool | None = None,
    results: list[dict] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "exit_code": exit_code,
        "dry_run": dry_run,
        "execution": execution,
        "task": task,
        "projects": projects,
        "plan": plan,
        "error": error,
        "approval_required": approval_required,
    }
    if results is not None:
        payload["results"] = results
    return payload


def cancelled_payload(*, dry_run: bool, task: str = "") -> dict[str, Any]:
    """JSON body for a cancelled command. No workers are started by this helper."""
    return _body(
        ok=False,
        status="cancelled",
        exit_code=130,
        dry_run=dry_run,
        execution="none",
        task=task,
        projects=[],
        plan=[],
        error="cancelled before any task ran",
    )


def _fail(
    status: str,
    code: int,
    message: str,
    *,
    task: str = "",
    approval_required: bool | None = None,
) -> tuple[int, dict[str, Any]]:
    return code, _body(
        ok=False,
        status=status,
        exit_code=code,
        dry_run=True,
        execution="none",
        task=task,
        projects=[],
        plan=[],
        error=message,
        approval_required=approval_required,
    )


def select_projects(registry, project_ids: str | None) -> tuple[list, str | None]:
    """Return enabled projects, or an error string. Does not touch the filesystem."""
    if project_ids is None or not str(project_ids).strip():
        chosen = list(registry.enabled())
        if not chosen:
            return [], "no enabled projects to plan"
        return chosen, None

    requested = [part.strip() for part in str(project_ids).split(",") if part.strip()]
    if not requested:
        return [], "no project ids given"
    by_id = {project.id: project for project in registry.projects}
    problems: list[str] = []
    chosen = []
    for project_id in requested:
        project = by_id.get(project_id)
        if project is None:
            problems.append(f"unknown project {project_id!r}")
        elif not project.enabled:
            problems.append(f"project {project_id!r} is disabled")
        else:
            chosen.append(project)
    if problems:
        return [], "; ".join(problems)
    return chosen, None


def run_dry_run(
    *,
    task: str,
    project_ids: str | None,
    output: str | None,
    load_settings: Callable[[], Any],
    load_projects: Callable[[], Any],
) -> tuple[int, dict[str, Any]]:
    """Build a JSON plan from local config.

    ``load_settings`` and ``load_projects`` are the only I/O, and they must be
    read-only. ``--output`` is rejected because writing the plan would be a
    filesystem change.
    """
    try:
        if output:
            return _fail(
                "unsupported",
                2,
                "dry-run does not accept --output because that flag writes a file",
                task=task or "",
            )
        if task is None or not str(task).strip():
            return _fail("unsupported", 2, "task is empty; pass --task with the text to plan")

        try:
            settings = load_settings()
            registry = load_projects()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            return _fail("error", 1, f"config error: {exc}", task=str(task).strip())
        approval = bool(settings.workspace.approval_required)
        chosen, problem = select_projects(registry, project_ids)
        if problem:
            return _fail("error", 1, problem, task=str(task).strip(), approval_required=approval)

        steps: list[dict] = []
        for project in chosen:
            agents = [name for name in _PLAN_AGENTS if getattr(project.tasks, name, False)]
            if not agents:
                return _fail(
                    "unsupported",
                    2,
                    f"project {project.id!r} has no monitor, coder, security, or content "
                    "task enabled; nothing to plan without executing",
                    task=str(task).strip(),
                    approval_required=approval,
                )
            steps.append({
                "project_id": project.id,
                "project_name": project.name,
                "agents": agents,
                "task": str(task).strip(),
                "executes": False,
            })

        text = str(task).strip()
        return 0, _body(
            ok=True,
            status="planned",
            exit_code=0,
            dry_run=True,
            execution="none",
            task=text,
            projects=[step["project_id"] for step in steps],
            plan=steps,
            error=None,
            approval_required=approval,
        )
    except KeyboardInterrupt:
        return 130, cancelled_payload(dry_run=True, task=str(task or ""))


def results_payload(results: list[dict], *, task: str) -> tuple[int, dict[str, Any]]:
    """JSON body for a finished live run. Empty results stay exit 0, matching `run`."""
    ok = all(item.get("success") for item in results) if results else True
    code = 0 if ok else 1
    return code, _body(
        ok=ok,
        status="ok" if ok else "error",
        exit_code=code,
        dry_run=False,
        execution="completed",
        task=task,
        projects=sorted({str(item.get("project", "")) for item in results if item.get("project")}),
        plan=[],
        error=None if ok else "one or more tasks failed",
        results=results,
    )
