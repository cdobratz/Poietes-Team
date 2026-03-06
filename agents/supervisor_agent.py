"""
agents/supervisor_agent.py — Orchestrates the specialist agents.
Parses high-level tasks, delegates to sub-agents, aggregates results,
and sends final reports via the messenger.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from agents.base import AgentResult, BaseAgent
from agents.monitor_agent import MonitorAgent
from agents.coder_agent import CoderAgent
from agents.security_agent import SecurityAgent
from agents.content_agent import ContentAgent
from agents.filesystem_agent import FilesystemAgent
from config.loader import Project, ProjectRegistry, Settings
from templates.loader import TaskTemplate

logger = logging.getLogger(__name__)


SUPERVISOR_SYSTEM_PROMPT = """
You are SupervisorAgent, an engineering team lead.
Given a high-level task description and a list of projects, determine which
specialist agents should run on which projects and in what order.

Respond ONLY as JSON:
{
  "plan": [
    {
      "project_id": "...",
      "agents": ["monitor", "security", "coder", "content", "filesystem"],
      "task": "...",
      "priority": 1
    }
  ],
  "parallel": true,
  "summary": "..."
}

Agent roles:
- monitor: code health, dead code, file stats, git status
- security: Bandit, Semgrep, dependency audits
- coder: feature implementation, bug fixes, refactoring
- content: README, changelog, docstrings
- filesystem: directory scanning, file search, tree structure, large file detection
"""


class SupervisorAgent(BaseAgent):
    """
    Top-level agent that:
    1. Parses user task with LLM
    2. Builds an execution plan
    3. Delegates to specialist agents
    4. Aggregates and reports results
    """

    name = "supervisor"

    def __init__(
        self,
        settings: Settings,
        registry: ProjectRegistry,
        memory=None,
        messenger=None,
    ):
        super().__init__(settings, memory, messenger)
        self.registry = registry
        self._agents: dict[str, BaseAgent] = {
            "monitor": MonitorAgent(settings, memory, messenger),
            "coder": CoderAgent(settings, memory, messenger),
            "security": SecurityAgent(settings, memory, messenger),
            "content": ContentAgent(settings, memory, messenger),
            "filesystem": FilesystemAgent(settings, memory, messenger),
        }

    # ── Planning ──────────────────────────────────────────────────────────

    def _build_plan(self, task: str, projects: list[Project]) -> dict:
        """Ask LLM to build a delegation plan."""
        project_list = [
            {"id": p.id, "name": p.name, "language": p.language, "labels": p.labels}
            for p in projects
        ]
        messages = [{
            "role": "user",
            "content": (
                f"Task: {task}\n\n"
                f"Available projects:\n{json.dumps(project_list, indent=2)}"
            ),
        }]
        raw = self._call_llm(messages, system=SUPERVISOR_SYSTEM_PROMPT)
        try:
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, AttributeError):
            # Fallback: run monitor on all projects
            return {
                "plan": [
                    {"project_id": p.id, "agents": ["monitor"], "task": task, "priority": 1}
                    for p in projects
                ],
                "parallel": True,
                "summary": "Fallback: monitor scan only",
            }

    # ── Execution ─────────────────────────────────────────────────────────

    def _execute_step(self, step: dict, project: Project) -> list[AgentResult]:
        """Run all assigned agents for a single plan step."""
        results = []
        task = step.get("task", "")
        for agent_name in step.get("agents", []):
            agent = self._agents.get(agent_name)
            if not agent:
                logger.warning(f"Unknown agent: {agent_name}")
                continue
            try:
                result = agent.run_task(project, task)
                results.append(result)
            except Exception as e:
                logger.exception(f"Agent {agent_name} failed on {project.id}: {e}")
                results.append(AgentResult(
                    agent_name=agent_name,
                    project_id=project.id,
                    task="error",
                    success=False,
                    summary=str(e),
                ))
        return results

    def _execute_plan(self, plan: dict, projects: list[Project]) -> list[AgentResult]:
        """Execute all plan steps, optionally in parallel."""
        steps = sorted(plan.get("plan", []), key=lambda s: s.get("priority", 99))
        parallel = plan.get("parallel", False)

        project_map = {p.id: p for p in projects}
        all_results: list[AgentResult] = []

        if parallel and len(steps) > 1:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(
                        self._execute_step, step, project_map[step["project_id"]]
                    ): step
                    for step in steps
                    if step["project_id"] in project_map
                }
                for future in as_completed(futures):
                    try:
                        all_results.extend(future.result())
                    except Exception as e:
                        logger.exception(f"Parallel step failed: {e}")
        else:
            for step in steps:
                project = project_map.get(step.get("project_id", ""))
                if not project:
                    continue
                all_results.extend(self._execute_step(step, project))

        return all_results

    # ── Reporting ─────────────────────────────────────────────────────────

    def _build_report(self, results: list[AgentResult], plan_summary: str) -> str:
        total = len(results)
        successes = sum(1 for r in results if r.success)
        failures = total - successes

        lines = [
            "=" * 60,
            "  AGENT TEAM REPORT",
            "=" * 60,
            f"Plan: {plan_summary}",
            f"Total: {total} tasks | ✅ {successes} succeeded | ❌ {failures} failed",
            "",
        ]

        by_project: dict[str, list[AgentResult]] = {}
        for r in results:
            by_project.setdefault(r.project_id, []).append(r)

        for pid, proj_results in by_project.items():
            lines.append(f"📁 {pid}")
            for r in proj_results:
                icon = "✅" if r.success else "❌"
                lines.append(f"  {icon} [{r.agent_name}] {r.summary}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    # ── Template execution ──────────────────────────────────────────────────

    def run_template(
        self,
        template: TaskTemplate,
        projects: list[Project] | None = None,
    ) -> list[AgentResult]:
        """
        Execute a task template deterministically (bypasses LLM planning).
        Each template step maps directly to a specialist agent.
        """
        if projects is None:
            projects = self.registry.enabled()

        if not projects:
            logger.warning("No enabled projects found")
            self.notify("No enabled projects to work on.")
            return []

        self.notify(
            f"Running template '{template.name}' on {len(projects)} project(s)"
        )

        all_results: list[AgentResult] = []

        for project in projects:
            logger.info(f"Template '{template.id}' on project '{project.id}'")
            for i, step in enumerate(template.steps, 1):
                agent = self._agents.get(step.agent)
                if not agent:
                    logger.warning(f"Unknown agent in template step: {step.agent}")
                    continue

                logger.info(f"  Step {i}/{len(template.steps)}: [{step.agent}] {step.task}")
                try:
                    result = agent.run_task(project, step.task)
                    all_results.append(result)
                except Exception as e:
                    logger.exception(f"Template step failed: {step.agent} on {project.id}")
                    all_results.append(AgentResult(
                        agent_name=step.agent,
                        project_id=project.id,
                        task=step.task,
                        success=False,
                        summary=str(e),
                    ))

        report = self._build_report(all_results, f"Template: {template.name}")
        print(report)
        self.notify(f"Template complete:\n{report}")

        return all_results

    # ── Main interface ─────────────────────────────────────────────────────

    def run_task(self, project: Project, task_description: str) -> AgentResult:
        """Run a single task on a single project (BaseAgent interface)."""
        results = self.run(task_description, projects=[project])
        success = all(r.success for r in results)
        return self._make_result(
            project=project,
            task="supervisor",
            success=success,
            summary=f"Delegated {len(results)} sub-tasks",
            details={"results": [r.to_dict() for r in results]},
        )

    def run(
        self,
        task: str,
        projects: list[Project] | None = None,
        on_result: Callable[[AgentResult], None] | None = None,
    ) -> list[AgentResult]:
        """
        Main entry point.
        Builds a plan, executes it, and returns all AgentResults.
        """
        if projects is None:
            projects = self.registry.enabled()

        if not projects:
            logger.warning("No enabled projects found")
            self.notify("⚠️ No enabled projects to work on.")
            return []

        self.notify(f"🚀 Supervisor starting: '{task}' on {len(projects)} project(s)")

        plan = self._build_plan(task, projects)
        logger.info(f"Plan: {json.dumps(plan, indent=2)}")

        results = self._execute_plan(plan, projects)

        if on_result:
            for r in results:
                on_result(r)

        report = self._build_report(results, plan.get("summary", ""))
        print(report)
        self.notify(f"📊 Run complete:\n{report}")

        # Save run summary to memory
        self.remember(
            key=f"run:{task[:40]}",
            value=json.dumps({
                "task": task,
                "projects": [p.id for p in projects],
                "success_rate": f"{sum(1 for r in results if r.success)}/{len(results)}",
            }),
        )

        return results
