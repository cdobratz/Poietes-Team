"""
config/loader.py — Loads and validates settings.yaml + projects.yaml.
Supports environment variable interpolation:
  ${VAR}          required — loading fails if VAR is unset
  ${VAR:-default} optional — uses "default" if VAR is unset or empty
Unknown config keys are rejected (typos fail loudly instead of being ignored).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings

CONFIG_DIR = Path(__file__).parent

# ─── Env-var interpolation ────────────────────────────────────────────────────

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    """Raised when configuration is invalid or incomplete."""


def _interpolate(obj: Any, strict: bool = True, _missing: list[str] | None = None) -> Any:
    """Recursively replace ${VAR} / ${VAR:-default} with os.environ values.

    In strict mode (default), every unset ``${VAR}`` without a default is collected
    and reported together in a ConfigError. Non-strict mode substitutes "".
    """
    top = _missing is None
    missing: list[str] = [] if _missing is None else _missing

    def walk(o: Any) -> Any:
        if isinstance(o, str):
            def _replace(m: re.Match) -> str:
                name, default = m.group(1), m.group(2)
                value = os.environ.get(name)
                if value:
                    return value
                if default is not None:
                    return default
                missing.append(name)
                return ""
            return _ENV_RE.sub(_replace, o)
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(i) for i in o]
        return o

    result = walk(obj)
    if top and strict and missing:
        names = ", ".join(sorted(set(missing)))
        raise ConfigError(
            f"Unset environment variable(s) referenced in config: {names}. "
            "Set them, or use ${VAR:-default} for optional values."
        )
    return result


def _load_yaml(path: Path, strict: bool = True) -> dict:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return _interpolate(raw or {}, strict=strict)


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class _StrictModel(BaseModel):
    """Base for all config models: unknown keys are errors, not silently ignored."""
    model_config = ConfigDict(extra="forbid")


class LLMBackend(_StrictModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


class LLMConfig(_StrictModel):
    default: str = "claude"
    backends: dict[str, LLMBackend] = {}


class AgentConfig(_StrictModel):
    llm: str = "claude"
    max_iterations: int = 20


class MCPServer(_StrictModel):
    url: str
    enabled: bool = False
    api_key: str = ""


class MCPConfig(_StrictModel):
    serena: MCPServer = MCPServer(url="http://localhost:8001/mcp")
    mem0: MCPServer = MCPServer(url="http://localhost:8002/mcp")
    playwright: MCPServer = MCPServer(url="http://localhost:8003/mcp")


class TelegramConfig(_StrictModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    # Additional chat IDs allowed to send commands (chat_id is always allowed).
    allowed_chat_ids: list[str] = Field(default_factory=list)
    # Max simultaneous /run tasks started from Telegram; extra requests are refused.
    max_concurrent_runs: int = Field(default=1, ge=1)


class MessagingConfig(_StrictModel):
    telegram: TelegramConfig = TelegramConfig()
    cli: dict = {"enabled": True, "verbose": True}


class GitHubConfig(_StrictModel):
    enabled: bool = False
    token: str = ""
    default_branch: str = "main"
    auto_pr: bool = False


class GitLabConfig(_StrictModel):
    enabled: bool = False
    token: str = ""
    url: str = "https://gitlab.com"


class GitConfig(_StrictModel):
    github: GitHubConfig = GitHubConfig()
    gitlab: GitLabConfig = GitLabConfig()


class WorkspaceConfig(_StrictModel):
    type: str = "local"
    sandbox_writes: bool = True
    approval_required: bool = True


class SecurityToolsConfig(_StrictModel):
    bandit: bool = True
    semgrep: bool = False
    safety: bool = True


class Settings(_StrictModel):
    llm: LLMConfig = LLMConfig()
    agents: dict[str, AgentConfig] = {}
    mcp: MCPConfig = MCPConfig()
    messaging: MessagingConfig = MessagingConfig()
    git: GitConfig = GitConfig()
    workspace: WorkspaceConfig = WorkspaceConfig()
    security: SecurityToolsConfig = SecurityToolsConfig()

    def get_agent_cfg(self, agent_name: str) -> AgentConfig:
        return self.agents.get(agent_name, AgentConfig())

    def get_llm_backend(self, name: str | None = None) -> LLMBackend:
        key = name or self.llm.default
        return self.llm.backends.get(key, LLMBackend(provider="anthropic", model="claude-sonnet-4-20250514"))


# ─── Project Models ───────────────────────────────────────────────────────────

class ProjectTasks(_StrictModel):
    monitor: bool = True
    coder: bool = True
    security: bool = True
    content: bool = True


class Project(_StrictModel):
    id: str
    name: str
    path: str = ""
    repo: str = ""
    branch: str = "main"
    language: str = "python"
    enabled: bool = True
    tasks: ProjectTasks = ProjectTasks()
    labels: list[str] = Field(default_factory=list)


class ProjectRegistry(_StrictModel):
    projects: list[Project] = []

    def enabled(self) -> list[Project]:
        return [p for p in self.projects if p.enabled]

    def by_id(self, project_id: str) -> Project | None:
        return next((p for p in self.projects if p.id == project_id), None)

    def for_task(self, task: str) -> list[Project]:
        """Return enabled projects that have a given task enabled."""
        return [
            p for p in self.enabled()
            if getattr(p.tasks, task, False)
        ]


# ─── Public loaders ───────────────────────────────────────────────────────────

def load_settings(path: Path | None = None) -> Settings:
    p = path or (CONFIG_DIR / "settings.yaml")
    if not p.exists():
        example = CONFIG_DIR / "settings.example.yaml"
        if example.exists():
            logger.warning(
                "config/settings.yaml not found — using settings.example.yaml "
                "(unset env vars become empty). Copy it to settings.yaml to configure."
            )
            data = _load_yaml(example, strict=False)
        else:
            data = {}
    else:
        data = _load_yaml(p)
    return Settings.model_validate(data)


def load_projects(path: Path | None = None) -> ProjectRegistry:
    p = path or (CONFIG_DIR / "projects.yaml")
    if not p.exists():
        example = CONFIG_DIR / "projects.example.yaml"
        if example.exists():
            logger.warning(
                "config/projects.yaml not found — using projects.example.yaml "
                "(example paths probably do not exist on this machine)."
            )
            data = _load_yaml(example, strict=False)
        else:
            data = {}
    else:
        data = _load_yaml(p)
    return ProjectRegistry.model_validate(data)
