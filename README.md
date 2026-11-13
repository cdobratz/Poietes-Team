# Poietes Multi-Agent Coding Team

![The Poietes multi-agent team collaborating on code: a pixel art illustration showing four stylized AI agents working together in a digital workspace, conveying teamwork, automation, and development activity in a friendly, approachable tone](images/final-pixel-art.jpg)

A modular, hierarchical AI agent system for autonomous software development, monitoring, security auditing, and content generation.

**Deploy autonomous coding workflows with intelligent memory management, extensible skills system, and workspace-scoped directory scanning.**

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Warp terminal workflow](#warp-terminal-workflow)
- [Features Guide](#features-guide)
- [Testing & Validation](#testing--validation)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

## Overview

Poietes is a multi-agent system that orchestrates AI-powered development workflows. The system consists of specialized agents that collaborate through a supervisor, each with distinct responsibilities:

- **Project scans**: file counts, TODO markers, git status, and outdated dependencies
- **Code edits**: the coder agent turns a task description into file operations
- **Security checks**: Bandit, Semgrep, and dependency output when those tools are enabled
- **Docs drafts**: README, changelog, and docstring text
- **Directory scans**: FilesystemAgent can scan a path that is not listed in `projects.yaml`
- **Skill list**: `python main.py skills list` prints modules from `skills/`
- **Memory**: agents use Mem0 when it is configured, and an in-process fallback otherwise

## Architecture

### Agent Hierarchy

```bash
SupervisorAgent (orchestrator)
├── MonitorAgent          - file stats, TODOs, git status, dependencies
├── CoderAgent            - file edits from a task, optional Serena context
├── SecurityAgent         - Bandit, Semgrep, dependency checks
├── ContentAgent          - README, changelog, docstrings
└── FilesystemAgent       - directory scan, search, tree, large files
```

### Data Flow

```md
┌─────────────┐
│    User     │ (CLI or Telegram)
└──────┬──────┘
       │ Task
       ▼
┌──────────────────────┐
│ SupervisorAgent      │ (routes tasks → agents)
└──────┬───────────────┘
       │
       ├──► MonitorAgent ──► Project Scan ──► Issues
       ├──► CoderAgent ──► Develop ──► Code
       ├──► SecurityAgent ──► Audit ──► Vulnerabilities
       ├──► ContentAgent ──► Generate ──► Docs
       └──► FilesystemAgent ──► Scan ──► File Tree
       
       All Agents ──► Skills ──► Actions
       All Agents ──► Memory ──► Recall/Store
```

## Key Features

### 1. FilesystemAgent: Workspace Directory Scanning

`fs` commands and filesystem tasks stay inside `workspace.root`. Paths that leave it are rejected. Set `workspace.root` before using `fs`; a supervisor or Telegram filesystem task is limited to the project path, and that path must sit inside `workspace.root` when it is set.

**Capabilities:**
- `scan_directory(path, pattern)` — Recursive directory scan with glob patterns
- `search_files(path, query)` — Content search (grep-like) across files
- `get_file_info(path)`: file metadata (size, modified time, type)
- `list_tree(path, max_depth)`: directory tree as nested data (the CLI prints JSON)
- `find_large_files(path, min_lines)` — Identify large/complex files

**Use Cases:**
- List files under a directory, with an optional glob
- Search file contents
- Show a directory tree
- List files over a line-count threshold

### 2. Skill modules

`skills/` holds modules that `python main.py skills list` can import. The agents do not load or call them.

A module exports a `skill` value:

```python
from skills.base import Skill

def do_something(**kwargs) -> dict:
    return {"success": True}

skill = Skill(
    name="example",
    description="Example skill",
    triggers=["example", "demo"],
    action=do_something,
)
```

**Bundled modules:**
- `github_skill.py`
- `gitlab_skill.py`
- `debug_skill.py`
- `deploy_skill.py`

The list command prints `name`, `description`, and `triggers` for each exported `skill`. The bundled action functions are local placeholders. They are not called by `python main.py run`.

### 3. Memory

Agents started from `main.py` store and recall through `SmartMemory` in `memory/smart_memory.py`. It scores text from keywords, keeps at most 50 important entries per project id, and `cleanup_low_value()` drops entries with score below 4 that are at least 7 days old. The text is also written to the configured client in `memory/mem0_client.py`. That client uses Mem0 when an API key or MCP URL is configured. Otherwise it keeps an in-process list that ends when the process exits. Importance scores stay on the `SmartMemory` object. `python main.py memory stats` and `python main.py memory cleanup` each create a new instance, so they do not show scores from another process.

```python
from memory.smart_memory import SmartMemory

memory = SmartMemory()

memory.remember_important(
    key="project_arch",
    value="Uses FastAPI + PostgreSQL",
    project_id="my-app",
    score=9,
)

important_facts = memory.recall_by_importance(min_score=7)
recent = memory.recall_recent(days=3)
removed = memory.cleanup_low_value()
```

## Technology Stack

| Layer       | Technology                          |
|-------------|-------------------------------------|
| **Agents**  | In-repo Python agents               |
| **LLMs**    | Claude / Grok / Ollama / MiniMax    |
| **Memory**  | Mem0 (semantic + traditional)       |
| **Code**    | Serena MCP (file operations)        |
| **Browser** | Playwright MCP                      |
| **Git**     | GitHub / GitLab (Personal Access Token) |
| **Messaging** | Telegram Bot + CLI               |
| **Runtime** | Local / Docker                      |
| **Language** | Python 3.10+                       |

## Prerequisites

- Python 3.10 or higher
- Docker & Docker Compose (for MCP servers)
- API Keys:
  - Anthropic API key (or alternative LLM provider)
  - GitHub Personal Access Token (optional, for Git integration)
  - Mem0 API key (optional, for cloud memory)
- Git (for repository operations)

## Quick Start

### 1. Clone and Install

```bash
git clone <repo> && cd poietes-team
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy configuration templates
cp config/settings.example.yaml config/settings.yaml
cp config/projects.example.yaml config/projects.yaml

# Edit with your values
nano config/settings.yaml
nano config/projects.yaml
```

### 3. Set Environment Variables

```bash
export ANTHROPIC_API_KEY="your-key-here"
export GITHUB_TOKEN="your-github-pat"
export MEM0_API_KEY="your-mem0-key"  # Optional
```

### 4. Start MCP Servers (Optional, for cloud services)

```bash
docker-compose -f docker/mcp-compose.yml up -d
```

### 5. Run

```bash
# Scan all configured projects
python main.py run --task "scan all projects for issues"

# Scan a directory inside workspace.root
python main.py fs scan .

# List available skills
python main.py skills list

# Validate configuration
python main.py validate
```

## Configuration

### settings.yaml

Copy `config/settings.example.yaml`. It sets LLM backends, agent model assignments, MCP servers, messaging, git tokens, workspace approval, and security tools.

```yaml
llm:
  default: claude
  backends:
    claude:
      provider: anthropic
      model: claude-sonnet-4-20250514
      api_key: "${ANTHROPIC_API_KEY}"

workspace:
  type: local
  root: "/workspace"            # fs commands cannot leave this directory
  approval_required: true       # skipped writes report awaiting_approval, not success

messaging:
  telegram:
    enabled: false
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
```

### projects.yaml

Copy `config/projects.example.yaml`. Each project needs an `id`, and can set `path`, `repo`, `language`, and per-agent `tasks`.

```yaml
projects:
  - id: api-backend
    name: "REST API Backend"
    path: "/workspace/api-backend"
    repo: "github.com/org/api-backend"
    branch: main
    language: python
    enabled: true
    tasks:
      monitor: true
      coder: true
      security: true
      content: true
```

Filesystem commands and tasks do not need the target listed in `projects.yaml`, but the path must stay inside `workspace.root`.

## Usage

### Command Line Interface

```bash
# Run a task with natural language
python main.py run --task "find all TODO comments in my project"

# Paths below are inside workspace.root
python main.py fs scan .
python main.py fs scan . --pattern "*.py"

# Search for content
python main.py fs search . "TODO"
python main.py fs search . "import os"

# Show directory tree
python main.py fs tree . --depth 3

# Find large files
python main.py fs large . --min-lines 500

# List available skills
python main.py skills list

# Memory operations
python main.py memory stats
python main.py memory cleanup

# Validate setup
python main.py validate
```

### Telegram Bot (If Enabled)

```txt
/run <task>: run a task (defaults to "scan all projects")
/status: reply that the agent team is running
```

### Python API

```python
from agents.supervisor_agent import SupervisorAgent
from config.loader import load_projects, load_settings

settings = load_settings()
registry = load_projects()
supervisor = SupervisorAgent(settings, registry)

results = supervisor.run("scan configured projects for security issues")
for result in results:
    print(result)
```

## Warp terminal workflow

This is a saved terminal workflow for running the Poietes CLI inside [Warp](https://docs.warp.dev/agents/cli-agents/overview/). It is not Warp agent management. Poietes is not one of the third-party CLI agents Warp detects, so it does not get the agent toolbelt, agent notifications, or a row in the Conversation Panel or Agent Management Panel. Sessions stay in the terminal pane where you ran the command. This change does not add an Agent Client Protocol (ACP) bridge.

Warp loads `.warp/workflows/*.yaml` when you open the repo and does not run those files until you select one. The plan workflow validates config, lists projects, and runs `python main.py run --dry-run`. It does not call the separate run workflow. Selecting the run workflow is the approval. There is no automatic yes.

`run --dry-run` prints one JSON plan and exits. It reads `settings.yaml` and `projects.yaml` only. It does not call an LLM, memory, messaging, or a subprocess, and it does not write files. `--output` with `--dry-run` is rejected (exit 2) because that flag would write a file. Unknown or disabled projects exit 1. A project with no monitor, coder, security, or content task exits 2. Cancellation exits 130. A real `run` still obeys `workspace.approval_required` and the filesystem sandbox; the dry-run does not enter that code.

### Working directory and isolated env

The current directory must be the repository root, the folder that contains `main.py` and `config/warp-trial`. Warp runs a workflow in the terminal's current directory. It has no cwd field.

```bash
cd /absolute/path/to/Poietes-Team
python3 -m venv .venv-warp
. .venv-warp/bin/activate
python -m pip install \
  "pydantic>=2.0.0" \
  "pydantic-settings>=2.0.0" \
  "pyyaml>=6.0" \
  "httpx>=0.26.0" \
  "tenacity>=8.2.0" \
  "typer>=0.9.0" \
  "rich>=13.0.0" \
  "python-dotenv>=1.0.0"
```

`.venv-warp/` is gitignored. This set is enough for `validate` and `run --dry-run`. It does not install an LLM client. Use another directory name if you already depend on `.venv`.

The trial config is `config/warp-trial`. Telegram is disabled and Mem0 is disabled there. Pointing `POIETES_CONFIG_DIR` at that directory does not edit `config/settings.yaml` or `config/projects.yaml`. If the variable is unset, the CLI uses `config/` as before. If the variable is set and `settings.yaml` is missing in that directory, loading fails instead of falling back.

Saved workflows (bash and zsh), from the [YAML workflow format](https://docs.warp.dev/terminal/entry/yaml-workflows/):

- `.warp/workflows/poietes-plan.yaml` arguments: `config_dir` (default `config/warp-trial`), `project_id` (required; fixture id `warp-fixture`), `task` (required).
- `.warp/workflows/poietes-run.yaml` is the real `python main.py run --json --task ... --projects ...`. Do not select it unless you intend to execute.

### Limits

- The plan lists the enabled agents for the project you named. It does not ask a model which agents should run.
- Filesystem scans are not part of the dry-run plan.
- A live `run` can call a configured LLM and is outside this trial.
- Ctrl-C during a parallel run stops waiting. Worker threads are daemons, so they do not keep the process alive after the command exits. Work already inside one agent is not killed mid-call.

### Troubleshooting

- `python` is not found, or import errors: the venv from this section is not active, or the current directory is not the repo root.
- Exit 1 and `unknown project`: `project_id` is not an enabled id in the selected config. The fixture id is `warp-fixture`.
- Exit 2: empty `--task`, `--output` combined with `--dry-run`, or the project has no planable tasks.
- Exit 130: cancelled. JSON status is `cancelled` and `execution` is `none`.
- `POIETES_CONFIG_DIR` error saying the default config was not used: that directory has no `settings.yaml` or `projects.yaml`.
- No Warp toolbelt or notification: expected. This CLI is not a Warp-managed agent.

### Manual acceptance

Owner: Cassidy. Automated tests did not perform a live or paid run. No tracker row was supplied for this slice.

From the repo root, with the env above active:

```bash
export POIETES_CONFIG_DIR="$PWD/config/warp-trial"
python main.py validate
python main.py run --dry-run --task "list configured agents" --projects warp-fixture
```

A real `python main.py run` without `--dry-run` needs a separate authorization.

## Features Guide

### MonitorAgent

For a project with a local path, the monitor collects:
- File counts, line counts, and TODO, FIXME, and HACK markers
- Files longer than 500 lines
- Git status and recent commits
- Outdated packages from `pip list --outdated` (Python) or `npm outdated` (JavaScript or TypeScript), when those commands succeed

An LLM call then summarizes that report. There is no scheduled scanner in this repo.

### CoderAgent

Given a task string, the coder asks the LLM for a plan and file operations (`replace`, `insert`, `delete`, `create`). Serena context is included only when the Serena MCP server is enabled. When `workspace.approval_required` is true, planned writes are skipped. That result is not success: `success` is false and `details["status"]` is `awaiting_approval`.

### SecurityAgent

When the matching flag in `settings.security` is true, the security agent runs Bandit, Semgrep, and a dependency command. Python uses `pip-audit`, and falls back to `safety` if `pip-audit` is not installed. JavaScript and TypeScript use `npm audit`. An LLM call summarizes the tool output. If a tool is disabled or missing, that part of the report is empty.

### ContentAgent Documentation Generation

Generates:
- README files
- CHANGELOG entries
- Docstrings

`run_task` writes a README when the task mentions `readme` or is empty, a changelog when the task mentions `changelog` or is empty, and docstrings when the task mentions `docstring` or `docs`. Files are written only when `workspace.approval_required` is false. When approval is required and there is something to write, the result is `success=False` with `details["status"]` `awaiting_approval`.

### FilesystemAgent

`scan_directory`, `search_files`, `get_file_info`, `list_tree`, and `find_large_files` only read inside `workspace.root`. The CLI commands are `fs scan`, `fs search`, `fs info`, `fs tree`, and `fs large`; they exit if `workspace.root` is unset. Supervisor and Telegram filesystem tasks use the project path, which must be inside `workspace.root` when that setting is set.

## Testing & Validation

### Validate Configuration

```bash
python main.py validate
```

Checks:
- `config/settings.yaml` loads, or `config/settings.example.yaml` when settings are missing
- `config/projects.yaml` loads, or `config/projects.example.yaml` when the projects file is missing, and the enabled project count is printed
- The default LLM backend name is printed
- A missing API key is reported when the provider is not Ollama

### Test FilesystemAgent

```bash
# Paths are inside workspace.root
python main.py fs scan .
python main.py fs search . "TODO"
python main.py fs tree . --depth 2
python main.py fs large . --min-lines 300
```

### List skills

```bash
python main.py skills list
```

This imports skill modules from `skills/` and prints them. It does not run skill actions.

### Call SmartMemory directly

```python
from memory.smart_memory import SmartMemory

m = SmartMemory()
m.remember_important("test", "important info", project_id="test")
print(m.recall_by_importance(min_score=5))
m.cleanup_low_value()
```

This object lives only in the current process. It is not the store agents use.

### Run a supervisor task

```bash
python main.py run --task "scan my project for issues, find security vulnerabilities, and generate a report"
```

`run` needs `config/settings.yaml`, `config/projects.yaml`, and a reachable LLM. It is not part of the pytest suite.

### Automated tests

`tests/test_agents.py` exercises monitor, coder, security, and content agents with a mocked LLM, plus the in-process memory fallback. `tests/test_templates.py` loads the YAML templates in `templates/`. Run them with `pytest`.

## Project Structure

```bash
poietes-team/
├── agents/                      # Agent implementations
│   ├── __init__.py
│   ├── base.py                 # Base class for all agents
│   ├── supervisor_agent.py     # Orchestrator
│   ├── monitor_agent.py        # Scanning & monitoring
│   ├── coder_agent.py          # Development
│   ├── security_agent.py       # Security auditing
│   ├── content_agent.py        # Documentation
│   └── filesystem_agent.py     # Directory scanning
├── skills/                      # Extensible skills system
│   ├── base.py                 # Skill base class & registry
│   ├── github_skill.py         # GitHub operations
│   ├── gitlab_skill.py         # GitLab operations
│   ├── debug_skill.py          # Debugging utilities
│   └── deploy_skill.py         # Deployment automation
├── memory/                      # Memory management
│   ├── __init__.py
│   ├── smart_memory.py         # Importance-weighted memory
│   └── mem0_client.py          # Mem0 integration
├── tools/                       # Utility tools
│   └── git_tools.py            # Git operations
├── config/                      # Configuration
│   ├── loader.py               # YAML parsing
│   ├── settings.example.yaml   # LLM and runtime settings
│   └── projects.example.yaml   # Project definitions
├── docker/                      # Docker support
│   ├── Dockerfile              # Container image
│   ├── docker-compose.yml      # Multi-container
│   └── mcp-compose.yml         # MCP servers only
├── tests/                       # Test suite
│   ├── test_agents.py
│   └── test_templates.py
├── main.py                      # CLI entry point
├── requirements.txt             # Python dependencies
├── LICENSE                      # Apache License 2.0
├── NOTICE                       # Copyright notice
└── README.md                    # This file
```

## Docker

### Single Container

```bash
docker build -f docker/Dockerfile -t poietes:latest .
docker run -v /path/to/config:/app/config poietes:latest
```

### Multi-Container (with MCP servers)

```bash
docker compose -f docker/docker-compose.yml up -d
```

## Contributing

Contributions are welcome! Here are common ways to extend Poietes:

### Add a New Skill

1. Create `skills/my_skill.py`:

```python
from skills.base import Skill

def do_something(**kwargs) -> dict:
    return {"status": "success"}

skill = Skill(
    name="My Skill",
    description="Short description",
    triggers=["keyword1", "keyword2"],
    action=do_something,
)
```

2. List it:

```bash
python main.py skills list
```

### Add a New Agent

1. Subclass `BaseAgent` in `agents/new_agent.py`
2. Construct it inside `SupervisorAgent` and add it to `self._agents`

### Improve Memory

- Add new query methods to `SmartMemory`
- Implement semantic search with embeddings
- Add project-specific memory strategies

### Report Issues

Include:
- Steps to reproduce
- Expected vs. actual behavior
- Config (settings.yaml, projects.yaml)
- Logs (if applicable)

## Support

- **Docs:** See README.md
- **Issues:** GitHub Issues
- **Discussions:** GitHub Discussions
- **Email:** info@poietes.org

## License

This project is open source under the Apache License 2.0. It is developed by Poietes LLC.

---

**Built with ❤️ for autonomous software development**
