"""
main.py — CLI entrypoint for the OpenHands multi-agent team.

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
from messaging.messenger import build_messenger
from agents.supervisor_agent import SupervisorAgent
from agents.filesystem_agent import FilesystemAgent
from templates.loader import list_templates, load_template
from tools.git_tools import GitManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

app = typer.Typer(help="OpenHands Multi-Agent Coding Team")
console = Console()


# ─── Shared context ───────────────────────────────────────────────────────────

def _build_supervisor(on_command=None) -> tuple[SupervisorAgent, any]:
    settings = load_settings()
    registry = load_projects()
    memory = build_memory_client(settings)
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
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only, no writes"),
):
    """Run a task across one or more projects."""
    supervisor, registry = _build_supervisor()

    if dry_run:
        supervisor.settings.workspace.approval_required = True

    target_projects = None
    if projects:
        ids = [p.strip() for p in projects.split(",")]
        target_projects = [p for p in registry.enabled() if p.id in ids]
        if not target_projects:
            console.print(f"[red]No matching projects found for: {projects}[/red]")
            raise typer.Exit(1)

    results = supervisor.run(task, projects=target_projects)

    if output:
        data = [r.to_dict() for r in results]
        Path(output).write_text(json.dumps(data, indent=2))
        console.print(f"[green]Results saved to {output}[/green]")

    success = all(r.success for r in results)
    raise typer.Exit(0 if success else 1)


@app.command()
def bot():
    """Start Telegram bot listener (polls for /run commands)."""
    settings = load_settings()
    if not settings.messaging.telegram.enabled:
        console.print("[yellow]Telegram is disabled in settings.yaml[/yellow]")
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

fs_app = typer.Typer(help="Filesystem operations (scan, search, tree, large files).")


@fs_app.command("scan")
def fs_scan(
    path: str = typer.Argument(..., help="Directory path to scan"),
    pattern: str = typer.Option(None, "--pattern", "-p", help="Glob pattern (e.g., *.py)"),
):
    """Scan a directory recursively."""
    settings = load_settings()
    fs_agent = FilesystemAgent(settings)
    
    console.print(f"[cyan]Scanning:[/cyan] {path}")
    result = fs_agent.scan_directory(path, pattern)
    
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
    """Search for text in files."""
    settings = load_settings()
    fs_agent = FilesystemAgent(settings)
    
    console.print(f"[cyan]Searching:[/cyan] {path} for '{query}'")
    result = fs_agent.search_files(path, query, file_pattern)
    
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
    """Show directory tree structure."""
    import json
    settings = load_settings()
    fs_agent = FilesystemAgent(settings)
    
    console.print(f"[cyan]Tree:[/cyan] {path}")
    tree = fs_agent.list_tree(path, depth)
    
    console.print(json.dumps(tree, indent=2))


@fs_app.command("large")
def fs_large(
    path: str = typer.Argument(..., help="Directory path"),
    min_lines: int = typer.Option(500, "--min-lines", "-n", help="Minimum line count"),
):
    """Find large files."""
    settings = load_settings()
    fs_agent = FilesystemAgent(settings)
    
    console.print(f"[cyan]Finding large files in:[/cyan] {path}")
    large_files = fs_agent.find_large_files(path, min_lines=min_lines)
    
    console.print(f"[green]✅[/green] Found {len(large_files)} large files")
    
    for f in large_files[:20]:
        console.print(f"  📄 {f.path} ({f.line_count} lines, {f.size / 1024:.1f} KB)")


@fs_app.command("info")
def fs_info(
    path: str = typer.Argument(..., help="File or directory path"),
):
    """Get file/directory info."""
    settings = load_settings()
    fs_agent = FilesystemAgent(settings)
    
    info = fs_agent.get_file_info(path)
    
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
    
    if not skills:
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
    
    console.print(table)


app.add_typer(skills_app, name="skills")


# ─── Memory Commands ────────────────────────────────────────────────────────────

memory_app = typer.Typer(help="Memory management commands.")


@memory_app.command("stats")
def memory_stats(project_id: str = typer.Option("", "--project", "-p", help="Project ID")):
    """Show memory statistics."""
    from memory.smart_memory import create_smart_memory
    
    sm = create_smart_memory()
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
    """Clean up low-value memories."""
    from memory.smart_memory import create_smart_memory
    
    sm = create_smart_memory()
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
