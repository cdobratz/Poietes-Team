# Poietes Multi-Agent Coding Team

![The Poietes multi-agent team collaborating on code: a pixel art illustration showing four stylized AI agents working together in a digital workspace, conveying teamwork, automation, and development activity in a friendly, approachable tone](images/final-pixel-art.jpg)

A modular, hierarchical AI agent system for autonomous software development, monitoring, security auditing, and content generation — built on OpenHands SDK.

**Deploy autonomous coding workflows with intelligent memory management, extensible skills system, and arbitrary directory scanning.**

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Features Guide](#features-guide)
- [Testing & Validation](#testing--validation)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

## Overview

Poietes is a production-ready multi-agent system that orchestrates AI-powered development workflows. The system consists of specialized agents that collaborate through a supervisor, each with distinct responsibilities:

- **Autonomous Scanning** — Monitor projects for issues, dead code, and architectural drift
- **Intelligent Development** — Generate features, fix bugs, and refactor code
- **Security Auditing** — Automated vulnerability detection and compliance checks
- **Content Generation** — Auto-generate documentation, changelogs, and READMEs
- **Arbitrary Directory Scanning** — Scan and analyze any local filesystem without pre-configuration
- **Extensible Skills** — Add new capabilities by dropping skill files into `skills/` directory
- **Smart Memory** — Persistent, importance-weighted memory with automatic cleanup

## Architecture

### Agent Hierarchy

```bash
SupervisorAgent (orchestrator)
├── MonitorAgent          — Project analysis, drift detection, dead code removal
├── CoderAgent            — Feature development, bug fixes, refactoring (via Serena MCP)
├── SecurityAgent         — Vulnerability scanning (Bandit, Semgrep, dependencies)
├── ContentAgent          — Documentation, changelogs, README generation
└── FilesystemAgent       — Arbitrary directory scanning and analysis
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

### 1. FilesystemAgent — Arbitrary Directory Scanning

Scan and analyze any local directory without pre-configuration.

**Capabilities:**
- `scan_directory(path, pattern)` — Recursive directory scan with glob patterns
- `search_files(path, query)` — Content search (grep-like) across files
- `get_file_info(path)` — File metadata (size, creation date, type)
- `list_tree(path, max_depth)` — Pretty-printed directory tree
- `find_large_files(path, min_lines)` — Identify large/complex files

**Use Cases:**
- Analyze unfamiliar codebases quickly
- Find technical debt (long files, TODO markers, dead imports)
- Locate configuration mismatches across environments
- Generate project structure reports

### 2. Skill System — Extensible Agent Capabilities

Define and register reusable skills that agents can discover and execute dynamically.

**How It Works:**

Each skill is a simple Python module in `skills/`:

```python
# skills/github_skill.py
from skills.base import Skill

class GitHubSkill(Skill):
    name = "GitHub Operations"
    description = "Create PRs, manage issues, review code"
    triggers = ["github", "pr", "pull request", "issue"]
    
    async def action(self, context: dict) -> dict:
        # Implementation
        pass
```

**Built-in Skills:**
- `github_skill.py` — GitHub PR/issue management
- `gitlab_skill.py` — GitLab operations
- `debug_skill.py` — Debugging helpers, log analysis
- `deploy_skill.py` — Deployment automation

**Adding New Skills:**

1. Create a new file in `skills/` with a `Skill` subclass
2. Define `name`, `description`, and `triggers`
3. Implement the `action()` method
4. Agents automatically discover and use it

No code changes needed — skills are loaded dynamically on agent initialization.

### 3. Smart Memory Management — Noise-Free Persistence

Intelligent, importance-weighted memory prevents unbounded growth while preserving critical context.

**Features:**

| Feature | Description |
|---------|------------|
| **Importance Scoring** | Memories scored 1-10 based on keywords and usage |
| **Auto-Cleanup** | Low-value memories (score < 4) expire after 7 days |
| **Project Isolation** | Max 50 important memories per project with LRU eviction |
| **Distinction** | "Remember" (persistent) vs "Context" (ephemeral) |
| **Semantic Search** | Query memories by meaning, not just keywords |

**Memory API:**

```python
from memory.smart_memory import SmartMemory

memory = SmartMemory()

# Store important findings
memory.remember_important(
    key="project_arch",
    value="Uses FastAPI + PostgreSQL",
    project_id="my-app",
    importance_score=9
)

# Query
important_facts = memory.recall_by_importance(min_score=7)
recent = memory.recall_recent(days=3)

# Cleanup (automatic, can also run manually)
memory.cleanup_low_value()
```

## Technology Stack

| Layer       | Technology                          |
|-------------|-------------------------------------|
| **Agents**  | OpenHands SDK                       |
| **LLMs**    | Claude / Grok / Ollama / MiniMax    |
| **Memory**  | Mem0 (semantic + traditional)       |
| **Code**    | Serena MCP (file operations)        |
| **Browser** | Playwright MCP                      |
| **Git**     | GitHub / GitLab (Personal Access Token) |
| **Messaging** | Telegram Bot + CLI               |
| **Runtime** | Local / Docker / Kubernetes         |
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

# Scan arbitrary directory
python main.py fs scan /path/to/any/project

# List available skills
python main.py skills list

# Validate configuration
python main.py validate
```

## Configuration

### settings.yaml

Controls LLM providers, API keys, memory behavior, and runtime settings.

```yaml
llm:
  provider: "anthropic"  # or: grok, ollama, minimax
  model: "claude-opus-4-1"
  temperature: 0.7

memory:
  enabled: true
  provider: "mem0"  # or: local
  max_per_project: 50
  cleanup_after_days: 7
  cleanup_interval: 3600  # seconds

agents:
  monitor:
    enabled: true
    scan_interval: 3600
  coder:
    enabled: true
  security:
    enabled: true
  content:
    enabled: true
  filesystem:
    enabled: true

workspace:
  type: "local"  # or: docker
  docker_image: "poietes:latest"

github:
  enabled: true
  api_token: "${GITHUB_TOKEN}"

telegram:
  enabled: false
  bot_token: "${TELEGRAM_BOT_TOKEN}"
```

### projects.yaml

Define target projects for monitoring and development.

```yaml
projects:
  - name: "my-api"
    path: "/workspace/my-api"
    repo_url: "https://github.com/user/my-api"
    branch: "main"
    type: "python"  # python, javascript, go, rust, etc.
    enable_security_scan: true
    enable_monitoring: true

  - name: "frontend-app"
    path: "/workspace/frontend-app"
    repo_url: "https://github.com/user/frontend-app"
    type: "javascript"
    enable_security_scan: true
```

Note: **FilesystemAgent doesn't require pre-configured projects** — it scans any path provided at runtime.

## Usage

### Command Line Interface

```bash
# Run a task with natural language
python main.py run --task "find all TODO comments in my project"

# Scan an arbitrary directory
python main.py fs scan /path/to/project
python main.py fs scan /path/to/project --pattern "*.py"

# Search for content
python main.py fs search /path "TODO"
python main.py fs search /path "import os"

# Show directory tree
python main.py fs tree /path --depth 3

# Find large files
python main.py fs find-large /path --min-lines 500

# List available skills
python main.py skills list
python main.py skills show github

# Memory operations
python main.py memory recall --min-importance 7
python main.py memory cleanup

# Validate setup
python main.py validate
```

### Telegram Bot (If Enabled)

```txt
/scan @my-api — scan project
/task create a feature for X — run a task
/status — show agent status
/memory recall — query memory
/help — show commands
```

### Python API

```python
from agents.supervisor_agent import SupervisorAgent
from config.config_loader import load_config

config = load_config()
supervisor = SupervisorAgent(config)

result = await supervisor.run_task(
    task="scan /workspace for security issues",
    project_id="my-app"
)
print(result)
```

## Features Guide

### MonitorAgent — Continuous Monitoring

Scans configured projects for:
- Dead code and unused imports
- Architectural drift
- Missing documentation
- Code complexity issues
- Dependency updates available
- Test coverage gaps

**Trigger keywords:** `monitor`, `scan`, `issues`, `drift`, `dead code`

### CoderAgent — Intelligent Development

Develops features through:
- Natural language specifications
- Automated code generation (via Serena MCP)
- Test-driven development
- Refactoring recommendations
- Bug fixing

**Trigger keywords:** `develop`, `feature`, `fix`, `refactor`, `implement`

### SecurityAgent — Vulnerability Detection

Audits with:
- Bandit (Python security)
- Semgrep (multi-language patterns)
- Dependency checker (CVE scanning)
- SAST/DAST analysis

**Trigger keywords:** `security`, `audit`, `vulnerabilities`, `scan`, `penetration`

### ContentAgent — Documentation Generation

Generates:
- API documentation
- CHANGELOG entries
- README updates
- Architecture diagrams
- Contributing guides

**Trigger keywords:** `docs`, `readme`, `changelog`, `document`, `generate`

### FilesystemAgent — Directory Analysis

Capabilities:
- Scan any directory without pre-configuration
- Find patterns, large files, duplicates
- Generate structure reports
- Identify technical debt markers

**Trigger keywords:** `scan`, `filesystem`, `directory`, `tree`, `search`

## Testing & Validation

### Validate Configuration

```bash
python main.py validate
```

Checks:
- ✅ API keys configured
- ✅ Projects exist on disk
- ✅ Git repositories reachable
- ✅ MCP servers running (if enabled)
- ✅ Skills loadable
- ✅ Memory configured correctly

### Test FilesystemAgent

```bash
# Scan a directory
python main.py fs scan /home/user/projects

# Search for patterns
python main.py fs search /home/user/projects "TODO"

# Get tree structure
python main.py fs tree /home/user/projects --depth 2

# Find large files
python main.py fs find-large /home/user/projects --min-lines 300
```

### Test Skills System

```bash
# List all loaded skills
python main.py skills list

# Show details for a skill
python main.py skills show github

# Run a task that triggers a skill
python main.py run --task "create a github pr for my feature"
```

### Test Memory System

```python
from memory.smart_memory import SmartMemory

# Test storage
m = SmartMemory()
m.remember_important("test", "important info", project_id="test")
print(m.recall_by_importance(min_score=5))

# Test cleanup
m.cleanup_low_value()
```

### Full Integration Test

```bash
# Run a complex task that uses multiple agents
python main.py run --task "scan my project for issues, find security vulnerabilities, and generate a report"
```

### Success Criteria

- ✅ FilesystemAgent scans any directory path
- ✅ Skills load automatically from `skills/` directory
- ✅ Agents use relevant skills based on task triggers
- ✅ Memory stores and recalls important information
- ✅ Low-value memories auto-cleanup after 7 days
- ✅ Memory limits prevent unbounded growth
- ✅ `python main.py validate` passes
- ✅ All components work via CLI and Python API

## Project Structure

```bash
poietes-team/
├── agents/                      # Agent implementations
│   ├── __init__.py
│   ├── base_agent.py           # Base class for all agents
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
│   ├── mem0_client.py          # Mem0 integration
│   └── cleanup.py              # Auto-cleanup logic
├── tools/                       # Utility tools
│   ├── git_tools.py            # Git operations
│   └── security_tools.py       # Security utilities
├── config/                      # Configuration
│   ├── config_loader.py        # YAML parsing
│   ├── settings.example.yaml   # LLM, memory settings
│   └── projects.example.yaml   # Project definitions
├── docker/                      # Docker support
│   ├── Dockerfile              # Container image
│   ├── docker-compose.yml      # Multi-container
│   └── mcp-compose.yml         # MCP servers only
├── tests/                       # Test suite
│   ├── test_agents.py
│   ├── test_skills.py
│   ├── test_memory.py
│   └── test_filesystem.py
├── main.py                      # CLI entry point
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Docker (Production)

### Single Container

```bash
docker build -t poietes:latest .
docker run -v /path/to/config:/app/config poietes:latest
```

### Multi-Container (with MCP servers)

```bash
docker-compose up -d
```

### Kubernetes

```bash
kubectl apply -f k8s/
```

## Contributing

Contributions are welcome! Here are common ways to extend Poietes:

### Add a New Skill

1. Create `skills/my_skill.py`:

```python
from skills.base import Skill

class MySkill(Skill):
    name = "My Skill"
    description = "Does something cool"
    triggers = ["keyword1", "keyword2"]
    
    async def action(self, context: dict) -> dict:
        # Your implementation
        return {"status": "success", "result": "..."}
```

2. Test it:

```bash
python main.py skills show my
python main.py run --task "keyword1 to do something"
```

### Add a New Agent

1. Subclass `BaseAgent` in `agents/new_agent.py`
2. Register it in `SupervisorAgent`
3. Define its triggers and responsibilities

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

## License

[Your License Here]

## Support

- **Docs:** See README.md and doc/
- **Issues:** GitHub Issues
- **Discussions:** GitHub Discussions
- **Email:** info@poietes.org

---

**Built with ❤️ for autonomous software development**
