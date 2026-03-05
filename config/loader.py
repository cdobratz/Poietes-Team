"""
config/loader.py — Loads and validates settings.yaml + projects.yaml.
Supports environment variable interpolation (${VAR_NAME} syntax).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

CONFIG_DIR = Path(__file__).parent

# ─── Env-var interpolation ────────────────────────────────────────────────────

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _interpolate(obj: Any) -> Any:
    """Recursively replace ${VAR} with os.environ values."""
    if isinstance(obj, str):
        def _replace(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_RE.sub(_replace, obj)
    if isinstance(obj, dict):
        return {k: _interpolate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate(i) for i in obj]
    return obj


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return _interpolate(raw or {})


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class LLMBackend(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


class LLMConfig(BaseModel):
    default: str = "claude"
    backends: dict[str, LLMBackend] = {}


class AgentConfig(BaseModel):
    llm: str = "claude"
    max_iterations: int = 20


class MCPServer(BaseModel):
    url: str
    enabled: bool = False
    api_key: str = ""


class MCPConfig(BaseModel):
    serena: MCPServer = MCPServer(url="http://localhost:8001/mcp")
    mem0: MCPServer = MCPServer(url="http://localhost:8002/mcp")
    playwright: MCPServer = MCPServer(url="http://localhost:8003/mcp")


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class MessagingConfig(BaseModel):
    telegram: TelegramConfig = TelegramConfig()
    cli: dict = {"enabled": True, "verbose": True}


class GitHubConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    default_branch: str = "main"
    auto_pr: bool = False


class GitLabConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    url: str = "https://gitlab.com"


class GitConfig(BaseModel):
    github: GitHubConfig = GitHubConfig()
    gitlab: GitLabConfig = GitLabConfig()


class WorkspaceConfig(BaseModel):
    type: str = "local"
    sandbox_writes: bool = True
    approval_required: bool = True


class SecurityToolsConfig(BaseModel):
    bandit: bool = True
    semgrep: bool = False
    safety: bool = True


class Settings(BaseModel):
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

class ProjectTasks(BaseModel):
    monitor: bool = True
    coder: bool = True
    security: bool = True
    content: bool = True


class Project(BaseModel):
    id: str
    name: str
    path: str = ""
    repo: str = ""
    branch: str = "main"
    language: str = "python"
    enabled: bool = True
    tasks: ProjectTasks = ProjectTasks()
    labels: list[str] = Field(default_factory=list)


class ProjectRegistry(BaseModel):
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
            data = _load_yaml(example)
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
            data = _load_yaml(example)
        else:
            data = {}
    else:
        data = _load_yaml(p)
    return ProjectRegistry.model_validate(data)
