"""
tools/git_tools.py — GitHub and GitLab integration.
Handles cloning, branch management, commits, and pull requests.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from config.loader import GitConfig, Project

logger = logging.getLogger(__name__)

# ─── Try github/gitlab SDKs ───────────────────────────────────────────────────
try:
    from github import Github, GithubException   # type: ignore
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False

try:
    import gitlab as gl                           # type: ignore
    GITLAB_AVAILABLE = True
except ImportError:
    GITLAB_AVAILABLE = False


# ─── Git subprocess helpers ───────────────────────────────────────────────────

def _git(args: list[str], cwd: str, env: dict | None = None) -> tuple[int, str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd, capture_output=True, text=True, timeout=60, env=run_env,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


class GitManager:
    """
    Handles git operations for a project.
    Works with both GitHub and GitLab via SDK or subprocess fallback.
    """

    def __init__(self, cfg: GitConfig):
        self.cfg = cfg
        self._gh = None
        self._glab = None

        if GITHUB_AVAILABLE and cfg.github.enabled and cfg.github.token:
            self._gh = Github(cfg.github.token)
            logger.info("GitHub client initialised")

        if GITLAB_AVAILABLE and cfg.gitlab.enabled and cfg.gitlab.token:
            self._glab = gl.Gitlab(cfg.gitlab.url, private_token=cfg.gitlab.token)
            logger.info("GitLab client initialised")

    # ── Cloning ───────────────────────────────────────────────────────────

    def ensure_cloned(self, project: Project, workspace: str = "/workspace") -> str:
        """Clone project if not already present. Returns local path."""
        if project.path and Path(project.path).exists():
            return project.path

        if not project.repo:
            raise ValueError(f"Project {project.id} has no repo configured")

        repo_url = self._build_clone_url(project)
        target = Path(workspace) / project.id
        target.mkdir(parents=True, exist_ok=True)

        if (target / ".git").exists():
            logger.info(f"Repo already cloned: {target}")
            rc, out = _git(["pull", "--rebase"], str(target))
            if rc != 0:
                logger.warning(f"git pull failed: {out}")
            return str(target)

        logger.info(f"Cloning {repo_url} → {target}")
        rc, out = _git(
            ["clone", "--branch", project.branch, repo_url, str(target)],
            cwd=workspace,
        )
        if rc != 0:
            raise RuntimeError(f"Clone failed: {out}")

        return str(target)

    def _build_clone_url(self, project: Project) -> str:
        repo = project.repo
        # Normalize: strip https:// prefix if present
        repo = repo.removeprefix("https://").removeprefix("http://")

        if repo.startswith("github.com"):
            token = self.cfg.github.token
            return f"https://{token}@{repo}.git" if token else f"https://{repo}.git"

        if repo.startswith("gitlab.com") or "gitlab" in repo:
            token = self.cfg.gitlab.token
            return f"https://oauth2:{token}@{repo}.git" if token else f"https://{repo}.git"

        return f"https://{repo}"

    # ── Branch management ─────────────────────────────────────────────────

    def create_branch(self, project_path: str, branch_name: str) -> bool:
        rc, out = _git(["checkout", "-b", branch_name], cwd=project_path)
        if rc != 0:
            logger.warning(f"Branch creation failed: {out}")
            return False
        return True

    def commit_changes(self, project_path: str, message: str, files: list[str] | None = None) -> bool:
        if files:
            for f in files:
                _git(["add", f], cwd=project_path)
        else:
            _git(["add", "-A"], cwd=project_path)

        rc, out = _git(["commit", "-m", message], cwd=project_path)
        if rc != 0:
            logger.warning(f"Commit failed: {out}")
            return False
        return True

    def push_branch(self, project_path: str, branch: str, remote: str = "origin") -> bool:
        rc, out = _git(
            ["push", "--set-upstream", remote, branch],
            cwd=project_path,
        )
        if rc != 0:
            logger.warning(f"Push failed: {out}")
            return False
        logger.info(f"Pushed branch {branch}")
        return True

    # ── Pull Requests ─────────────────────────────────────────────────────

    def open_pull_request(
        self,
        project: Project,
        head_branch: str,
        title: str,
        body: str,
    ) -> str | None:
        """Open a PR on GitHub or GitLab. Returns URL or None."""
        repo_str = project.repo

        if self._gh and "github.com" in repo_str:
            return self._open_github_pr(repo_str, head_branch, project.branch, title, body)

        if self._glab and ("gitlab.com" in repo_str or "gitlab" in repo_str):
            return self._open_gitlab_mr(repo_str, head_branch, project.branch, title, body)

        logger.warning("No Git SDK available for PR creation")
        return None

    def _open_github_pr(
        self, repo_str: str, head: str, base: str, title: str, body: str
    ) -> str | None:
        try:
            # Extract "owner/repo" from "github.com/owner/repo"
            parts = repo_str.replace("github.com/", "").strip("/").rstrip(".git")
            repo = self._gh.get_repo(parts)
            pr = repo.create_pull(title=title, body=body, head=head, base=base)
            logger.info(f"GitHub PR created: {pr.html_url}")
            return pr.html_url
        except Exception as e:
            logger.error(f"GitHub PR failed: {e}")
            return None

    def _open_gitlab_mr(
        self, repo_str: str, head: str, base: str, title: str, body: str
    ) -> str | None:
        try:
            path = repo_str.split("gitlab.com/")[-1].rstrip(".git")
            project = self._glab.projects.get(path)
            mr = project.mergerequests.create({
                "source_branch": head,
                "target_branch": base,
                "title": title,
                "description": body,
            })
            logger.info(f"GitLab MR created: {mr.web_url}")
            return mr.web_url
        except Exception as e:
            logger.error(f"GitLab MR failed: {e}")
            return None

    # ── Status helpers ────────────────────────────────────────────────────

    def current_branch(self, project_path: str) -> str:
        rc, out = _git(["branch", "--show-current"], cwd=project_path)
        return out if rc == 0 else "unknown"

    def has_changes(self, project_path: str) -> bool:
        rc, out = _git(["status", "--porcelain"], cwd=project_path)
        return rc == 0 and bool(out.strip())
