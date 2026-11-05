# Poietes Team

![The Poietes multi-agent team](images/final-pixel-art.jpg)

A small multi-agent CLI that monitors, audits, and proposes code changes across your projects. A supervisor routes a task to specialist agents and reports back on the CLI or Telegram.

Built by [Poietes LLC](https://poietes.org). Licensed under Apache-2.0.

## Safety defaults

- **Read-only by default.** `workspace.approval_required` is `true`, so the coder and content agents plan edits but write nothing. Set it to `false` only for projects you trust.
- **Writes stay inside the project.** Agent-supplied file paths go through `safe_join`. `../` and absolute paths are rejected.
- **Git tokens never go in URLs.** They are sent as an HTTP header and scrubbed from logs and errors.
- **Telegram is allowlisted.** Only `chat_id` and `allowed_chat_ids` can send commands. `max_concurrent_runs` caps parallel runs.
- **Config fails loudly.** An unset `${VAR}` is an error, `${VAR:-default}` sets a fallback, and unknown keys are rejected.

## Agents

| Agent | Does |
|---|---|
| Monitor | Project health, TODO and drift analysis |
| Coder | Plans edits, applies them only when approval is off |
| Security | Bandit, Semgrep, dependency audit |
| Content | Docs and changelog drafts |
| Filesystem | Scans any directory, no config needed |

LLM calls go through LiteLLM (Anthropic, xAI, Ollama, MiniMax). Memory is Mem0 cloud if `MEM0_API_KEY` is set, otherwise in-process and not persisted.

## Quick start

Requires Python 3.11+.

```bash
pip install -r requirements.txt
cp config/settings.example.yaml config/settings.yaml
cp config/projects.example.yaml config/projects.yaml
export ANTHROPIC_API_KEY=...        # the only required variable
python main.py validate
python main.py run --task "scan all projects" --dry-run
```

`scripts/setup.sh` does the install and copies the config for you.

## Commands

```text
python main.py run --task "..." [--projects id1,id2] [--output out.json] [--dry-run]
python main.py run-template <id> [--vars k=v,...] [--projects ...] [--dry-run]
python main.py list-templates
python main.py list-projects
python main.py validate
python main.py clone <project-id>
python main.py bot                      # Telegram listener: /run <task>, /status
python main.py fs scan|search|tree|large|info <path>
python main.py skills list
python main.py memory stats|cleanup
```

Templates live in `templates/` (`full_audit`, `implement_feature`, `onboard_project`, `security_fix`).

## Configuration

- `config/settings.yaml`: LLM backends, agent assignments, Telegram, Git tokens, workspace and security options.
- `config/projects.yaml`: the projects to work on.

Both are git-ignored. Keep secrets in environment variables and reference them as `${VAR}`.

For Telegram, set `messaging.telegram.enabled: true`, plus `bot_token` and `chat_id`.

## Docker

```bash
docker compose -f docker/docker-compose.yml run --rm agent-runner
docker compose -f docker/docker-compose.yml --profile telegram up -d telegram-bot
```

Containers run as a non-root user with no Docker socket. Config is mounted read-only. The runner is one-shot and does not restart.

## Skills

`skills/` is a plugin point. `debug` has working `analyze_error` and `format_exception`. The `github`, `gitlab`, and `deploy` skills are **stubs** that return `{"success": false, "not_implemented": true}`.

## Development

```bash
pip install pytest pytest-asyncio
pytest
```

## License

Apache-2.0. Copyright 2026 Poietes LLC. See [LICENSE](LICENSE).
