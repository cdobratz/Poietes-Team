"""
main.py: CLI entrypoint for the Poietes multi-agent team.

Usage:
  python main.py run --task "scan all projects for security issues"
  python main.py run --task "add dark mode to frontend-app"
  python main.py run --task "generate changelogs" --projects frontend-app,api-backend
  python main.py bot               # start Telegram bot listener
  python main.py list-projects     # show all configured projects
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

# ─── Bootstrap ────────────────────────────────────────────────────────────────
load_dotenv()

# Ensure config dir is on path
sys.path.insert(0, str(Path(__file__).parent))

from config.loader import load_settings, load_projects
from memory.mem0_client import build_memory_client
from memory.smart_memory import SmartMemory
from messaging.messenger import build_messenger
from agents.supervisor_agent import SupervisorAgent
from agents.filesystem_agent import FilesystemAgent
from templates.loader import list_templates, load_template
from tools.git_tools import GitManager
from tools.offline_plan import cancelled_payload, results_payload, run_dry_run
from tools.safe_paths import UnsafePathError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

app = typer.Typer(help="Poietes multi-agent coding team")
console = Console()


# ─── Shared context ───────────────────────────────────────────────────────────

def _build_supervisor(on_command=None) -> tuple[SupervisorAgent, any]:
    settings = load_settings()
    registry = load_projects()
    # Same SmartMemory type the `memory` CLI builds, wrapped around the configured store.
    memory = SmartMemory(backend=build_memory_client(settings))
    messenger = build_messenger(settings.messaging, on_command=on_command)
    supervisor = SupervisorAgent(settings, registry, memory=memory, messenger=messenger)
    return supervisor, registry


# ─── Commands ─────────────────────────────────────────────────────────────────

@app.command()
def run(
    task: str = typer.Option(..., "--task", "-t", help="High-level task description"),
    projects: Optional[str] = typer.Option(
        None, "--projects", "-p",
        help="Comma-separated project IDs (default: all enabled)"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Save results JSON to file"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print a read-only JSON plan and exit. Does not call an LLM or write files.",
    ),
    json_output: bool = typer.Option(
        False, "--json",
        help="Print one JSON document on stdout and skip the text report for this process.",
    ),
):
    """Run a task across one or more projects."""
    if dry_run:
        code, payload = run_dry_run(
            task=task,
            project_ids=projects,
            output=output,
            load_settings=load_settings,
            load_projects=load_projects,
        )
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        raise typer.Exit(code)

    try:
        supervisor, registry = _build_supervisor()

        target_projects = None
        if projects:
            ids = [p.strip() for p in projects.split(",")]
            target_projects = [p for p in registry.enabled() if p.id in ids]
            if not target_projects:
                console.print(f"[red]No matching projects found for: {projects}[/red]")
                raise typer.Exit(1)

        results = supervisor.run(task, projects=target_projects, quiet=json_output)
    except KeyboardInterrupt:
        if json_output:
            sys.stdout.write(json.dumps(cancelled_payload(dry_run=False, task=task), indent=2) + "\n")
        else:
            console.print("[yellow]Cancelled. No further workers will be started.[/yellow]")
        raise typer.Exit(130)

    if output:
        data = [r.to_dict() for r in results]
        Path(output).write_text(json.dumps(data, indent=2))
        console.print(f"[green]Results saved to {output}[/green]")

    if json_output:
        code, payload = results_payload([r.to_dict() for r in results], task=task)
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        raise typer.Exit(code)

    success = all(r.success for r in results)
    raise typer.Exit(0 if success else 1)


@app.command()
def bot():
    """Start Telegram bot listener (polls for /run commands)."""
    settings = load_settings()
    if not settings.messaging.telegram.enabled:
        console.print("[yellow]Telegram is disabled in settings.yaml[/yellow]")
        raise typer.Exit(1)

    tg = settings.messaging.telegram
    if not (tg.chat_id or tg.allowed_chat_ids):
        console.print(
            "[red]Refusing to start: set messaging.telegram.chat_id (or allowed_chat_ids) "
            "so only your chat can send commands.[/red]"
        )
        raise typer.Exit(1)

    console.print("[cyan]Starting Telegram bot...[/cyan]")

    supervisor_ref: list = []

    def on_command(task: str):
        if supervisor_ref:
            supervisor_ref[0].run(task)

    supervisor, _ = _build_supervisor(on_command=on_command)
    supervisor_ref.append(supervisor)
    supervisor.messenger.start_polling()

    console.print("[green]Bot running. Send /run <task> on Telegram.[/green]")
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("[yellow]Bot stopped.[/yellow]")


@app.command("list-projects")
def list_projects():
    """List all configured projects."""
    registry = load_projects()
    table = Table(title="Configured Projects", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Language")
    table.add_column("Enabled", justify="center")
    table.add_column("Tasks")
    table.add_column("Repo")

    for p in registry.projects:
        enabled_icon = "✅" if p.enabled else "❌"
        tasks = []
        for t in ("monitor", "coder", "security", "content"):
            if getattr(p.tasks, t, False):
                tasks.append(t)
        table.add_row(
            p.id, p.name, p.language, enabled_icon, ", ".join(tasks), p.repo or "—"
        )

    console.print(table)


@app.command()
def clone(
    project_id: str = typer.Argument(..., help="Project ID to clone"),
    workspace: str = typer.Option("/workspace", help="Target workspace directory"),
):
    """Clone a project's repository locally."""
    settings = load_settings()
    registry = load_projects()
    project = registry.by_id(project_id)

    if not project:
        console.print(f"[red]Project not found: {project_id}[/red]")
        raise typer.Exit(1)

    git = GitManager(settings.git)
    try:
        path = git.ensure_cloned(project, workspace)
        console.print(f"[green]Cloned to: {path}[/green]")
    except Exception as e:
        console.print(f"[red]Clone failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("list-templates")
def list_templates_cmd():
    """List all available agent task templates."""
    templates = list_templates()
    if not templates:
        console.print("[yellow]No templates found in templates/ directory.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Agent Task Templates", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Steps", justify="center")
    table.add_column("Variables")

    for t in templates:
        table.add_row(
            t.id,
            t.name,
            t.description[:60] + ("..." if len(t.description) > 60 else ""),
            str(len(t.steps)),
            ", ".join(t.variables) if t.variables else "—",
        )

    console.print(table)


# ─── Filesystem Commands ───────────────────────────────────────────────────────

fs_app = typer.Typer(
    help="Filesystem operations inside workspace.root (scan, search, tree, large files)."
)


def _filesystem_agent() -> FilesystemAgent:
    """CLI filesystem commands have no project, so workspace.root is required."""
    settings = load_settings()
    agent = FilesystemAgent(settings)
    try:
        agent.effective_root(None)
    except UnsafePathError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    return agent


def _guard_fs(action):
    try:
        return action()
    except UnsafePathError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@fs_app.command("scan")
def fs_scan(
    path: str = typer.Argument(..., help="Directory path to scan, inside workspace.root"),
    pattern: str = typer.Option(None, "--pattern", "-p", help="Glob pattern (e.g., *.py)"),
):
    """Scan a directory recursively inside the configured workspace."""
    fs_agent = _filesystem_agent()

    console.print(f"[cyan]Scanning:[/cyan] {path}")
    result = _guard_fs(lambda: fs_agent.scan_directory(path, pattern))
    
    console.print(f"[green]✅[/green] {result.total_files} files, {result.total_dirs} directories")
    console.print(f"[green]📊[/green] Total size: {result.total_size / 1024:.1f} KB")
    
    if result.files:
        console.print("\n[bold]Files:[/bold]")
        for f in result.files[:20]:
            icon = "📁" if f.is_dir else "📄"
            console.print(f"  {icon} {f.path}")
        if len(result.files) > 20:
            console.print(f"  ... and {len(result.files) - 20} more")


@fs_app.command("search")
def fs_search(
    path: str = typer.Argument(..., help="Directory to search"),
    query: str = typer.Argument(..., help="Search pattern (regex)"),
    file_pattern: str = typer.Option(None, "--pattern", "-p", help="File pattern (e.g., *.py)"),
):
    """Search for text in files inside the configured workspace."""
    fs_agent = _filesystem_agent()

    console.print(f"[cyan]Searching:[/cyan] {path} for '{query}'")
    result = _guard_fs(lambda: fs_agent.search_files(path, query, file_pattern))
    
    console.print(f"[green]✅[/green] {result.total_matches} matches in {result.files_matched} files")
    
    for match in result.matches[:10]:
        console.print(f"\n[bold]📄 {match['file']}[/bold]")
        for m in match["matches"][:5]:
            console.print(f"  Line {m['line']}: {m['content'][:80]}")


@fs_app.command("tree")
def fs_tree(
    path: str = typer.Argument(..., help="Directory path"),
    depth: int = typer.Option(3, "--depth", "-d", help="Maximum depth"),
):
    """Show directory tree structure inside the configured workspace."""
    import json
    fs_agent = _filesystem_agent()

    console.print(f"[cyan]Tree:[/cyan] {path}")
    tree = _guard_fs(lambda: fs_agent.list_tree(path, depth))
    
    console.print(json.dumps(tree, indent=2))


@fs_app.command("large")
def fs_large(
    path: str = typer.Argument(..., help="Directory path"),
    min_lines: int = typer.Option(500, "--min-lines", "-n", help="Minimum line count"),
):
    """Find large files inside the configured workspace."""
    fs_agent = _filesystem_agent()

    console.print(f"[cyan]Finding large files in:[/cyan] {path}")
    large_files = _guard_fs(lambda: fs_agent.find_large_files(path, min_lines=min_lines))
    
    console.print(f"[green]✅[/green] Found {len(large_files)} large files")
    
    for f in large_files[:20]:
        console.print(f"  📄 {f.path} ({f.line_count} lines, {f.size / 1024:.1f} KB)")


@fs_app.command("info")
def fs_info(
    path: str = typer.Argument(..., help="File or directory path"),
):
    """Get file/directory info inside the configured workspace."""
    fs_agent = _filesystem_agent()

    info = _guard_fs(lambda: fs_agent.get_file_info(path))
    
    if info:
        console.print(f"[bold]Path:[/bold] {info.path}")
        console.print(f"[bold]Type:[/bold] {'Directory' if info.is_dir else 'File'}")
        console.print(f"[bold]Size:[/bold] {info.size / 1024:.1f} KB")
        console.print(f"[bold]Modified:[/bold] {info.modified}")
        if info.extension:
            console.print(f"[bold]Extension:[/bold] {info.extension}")
        if info.line_count:
            console.print(f"[bold]Lines:[/bold] {info.line_count}")
    else:
        console.print(f"[red]Could not get info for: {path}[/red]")


app.add_typer(fs_app, name="fs")


# ─── Skills Commands ────────────────────────────────────────────────────────────

skills_app = typer.Typer(help="Skill management commands.")


@skills_app.command("list")
def skills_list():
    """List all available skills."""
    from pathlib import Path
    from skills.base import SkillRegistry, init_skill_registry
    
    # Initialize registry with skills directory
    skills_dir = Path(__file__).parent / "skills"
    registry = init_skill_registry(str(skills_dir))
    
    skills = registry.list_all()
    gated = [s for s in registry.list_all(include_unimplemented=True) if not s.implemented]

    if not skills and not gated:
        console.print("[yellow]No skills found.[/yellow]")
        raise typer.Exit(0)
    
    table = Table(title="Available Skills", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="dim")
    table.add_column("Description")
    table.add_column("Triggers")
    
    for skill in skills:
        table.add_row(
            skill.name,
            skill.description[:50] + ("..." if len(skill.description) > 50 else ""),
            ", ".join(skill.triggers[:5]),
        )
    
    if skills:
        console.print(table)
    if gated:
        names = ", ".join(s.name for s in gated)
        console.print(
            f"[yellow]Gated (not implemented, hidden from agents): {names}[/yellow]"
        )


app.add_typer(skills_app, name="skills")


# ─── Memory Commands ────────────────────────────────────────────────────────────

memory_app = typer.Typer(help="Memory management commands.")


@memory_app.command("stats")
def memory_stats(project_id: str = typer.Option("", "--project", "-p", help="Project ID")):
    """Show memory statistics for the configured memory backend."""
    from memory.smart_memory import build_smart_memory

    sm = build_smart_memory(load_settings())
    stats = sm.get_stats(project_id=project_id if project_id else "")
    
    console.print("[bold]Memory Statistics[/bold]")
    console.print(f"Total memories: {stats['total']}")
    console.print(f"  - Important: {stats['important']}")
    console.print(f"  - Context: {stats['context']}")
    console.print(f"Average score: {stats['average_score']}")
    console.print(f"High importance: {stats['high_importance']}")
    console.print(f"Medium importance: {stats['medium_importance']}")
    console.print(f"Low importance: {stats['low_importance']}")
    console.print(f"Max per project: {stats['max_per_project']}")


@memory_app.command("cleanup")
def memory_cleanup():
    """Clean up low-value memories on the configured memory backend."""
    from memory.smart_memory import build_smart_memory

    sm = build_smart_memory(load_settings())
    cleaned = sm.cleanup_low_value()
    summarized = sm.summarize_old_memories()
    
    console.print(f"[green]Cleaned up {cleaned} low-value memories[/green]")
    console.print(f"[green]Summarized {summarized} old memories[/green]")


app.add_typer(memory_app, name="memory")


@app.command("run-template")
def run_template_cmd(
    template_id: str = typer.Argument(..., help="Template ID (e.g. full_audit)"),
    vars: Optional[str] = typer.Option(
        None, "--vars", "-v",
        help="Comma-separated key=val pairs (e.g. project=myapp,feature=auth)"
    ),
    projects: Optional[str] = typer.Option(
        None, "--projects", "-p",
        help="Comma-separated project IDs (default: all enabled)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show plan only, no execution"),
):
    """Run a predefined agent task template."""
    # Parse variables
    variables: dict[str, str] = {}
    if vars:
        for pair in vars.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                variables[k.strip()] = v.strip()

    try:
        template = load_template(template_id, variables)
    except FileNotFoundError:
        console.print(f"[red]Template not found: {template_id}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Template:[/cyan] {template.name}")
    console.print(f"[cyan]Steps:[/cyan] {len(template.steps)}")
    for i, step in enumerate(template.steps, 1):
        console.print(f"  {i}. [{step.agent}] {step.task}")

    if dry_run:
        console.print("[yellow]Dry run — no execution.[/yellow]")
        raise typer.Exit(0)

    supervisor, registry = _build_supervisor()

    target_projects = None
    if projects:
        ids = [p.strip() for p in projects.split(",")]
        target_projects = [p for p in registry.enabled() if p.id in ids]
        if not target_projects:
            console.print(f"[red]No matching projects found for: {projects}[/red]")
            raise typer.Exit(1)

    results = supervisor.run_template(template, projects=target_projects)

    success = all(r.success for r in results)
    raise typer.Exit(0 if success else 1)


@app.command()
def validate():
    """Validate settings.yaml and projects.yaml configuration."""
    try:
        settings = load_settings()
        registry = load_projects()
        console.print(f"[green]✅ Settings valid[/green]")
        console.print(f"[green]✅ {len(registry.projects)} project(s) loaded ({len(registry.enabled())} enabled)[/green]")
        console.print(f"[green]✅ Default LLM: {settings.llm.default}[/green]")

        # Warn about missing keys
        backend = settings.get_llm_backend()
        if not backend.api_key and backend.provider != "ollama":
            console.print(f"[yellow]⚠️  No API key for '{settings.llm.default}' backend[/yellow]")

    except Exception as e:
        console.print(f"[red]❌ Config error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
