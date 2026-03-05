# OpenHands Multi-Agent Coding Team

A modular, hierarchical AI agent system for autonomous software development,
monitoring, security auditing, and content generation — built on OpenHands SDK.

## Architecture

```
SupervisorAgent
├── MonitorAgent      — scans projects for issues, dead code, drift
├── CoderAgent        — feature development via Serena MCP
├── SecurityAgent     — audits with Bandit, Semgrep, dependency checks
└── ContentAgent      — docs, changelogs, README generation
```

## Stack

| Layer       | Technology                          |
|-------------|-------------------------------------|
| Agents      | OpenHands SDK                       |
| LLMs        | Claude / Grok / Ollama / MiniMax    |
| Code tools  | Serena MCP                          |
| Memory      | Mem0 MCP                            |
| Browser     | Playwright MCP                      |
| Messaging   | Telegram Bot + CLI                  |
| Git         | GitHub / GitLab (PAT)               |
| Runtime     | Local → Docker → Kubernetes         |

## Quick Start

```bash
# 1. Clone & install
git clone <repo> && cd openhands-agent-team
pip install -r requirements.txt

# 2. Configure
cp config/settings.example.yaml config/settings.yaml
cp config/projects.example.yaml config/projects.yaml
# Edit both files with your keys and project paths

# 3. Start MCP servers
docker-compose -f docker/mcp-compose.yml up -d

# 4. Run
python main.py run --task "scan all projects for issues"
```

## Docker (Production)

```bash
docker-compose up -d
```

## Project Config

Add/remove projects dynamically via `config/projects.yaml`.
No code changes required — agents reload config on each run.
