"""
tools/run_cmd.py — One subprocess runner for agent shell-outs.

Callers keep their own timeouts, return codes, and messages. This module only
owns the subprocess call and classifies timeout / missing-binary / other errors
so those branches cannot drift apart.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass
class CmdResult:
    """Raw subprocess outcome. ``error`` is set only when the process did not start."""

    returncode: int
    stdout: str
    stderr: str
    error: str | None = None  # "timeout" | "not_found" | "error"
    error_detail: str = ""

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


def run_cmd(
    cmd: list[str],
    cwd: str,
    *,
    timeout: float = 120,
    env: dict[str, str] | None = None,
    inherit_env: bool = False,
    git_no_prompt: bool = False,
) -> CmdResult:
    """Run ``cmd`` in ``cwd``.

    ``inherit_env`` copies the current environment (needed for git auth vars).
    ``git_no_prompt`` sets ``GIT_TERMINAL_PROMPT=0`` when it is not already set.
    Exceptions are returned on the result; this function does not raise them.
    """
    run_env = None
    if inherit_env or env or git_no_prompt:
        run_env = os.environ.copy()
        if git_no_prompt:
            run_env.setdefault("GIT_TERMINAL_PROMPT", "0")
        if env:
            run_env.update(env)
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
        )
        return CmdResult(
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        return CmdResult(1, "", "", error="timeout", error_detail=str(exc))
    except FileNotFoundError as exc:
        return CmdResult(127, "", "", error="not_found", error_detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — last-resort so callers never see a raise
        return CmdResult(1, "", "", error="error", error_detail=str(exc))
