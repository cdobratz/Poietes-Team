"""
tools/git_tools.py — GitHub and GitLab integration.
Handles cloning, branch management, commits, and pull requests.
"""
from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

from config.loader import GitConfig, Project
from tools.run_cmd import run_cmd

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

_URL_CREDS_RE = re.compile(r"(https?://)[^/@\s]+@")


def scrub_secrets(text: str, secrets: tuple[str, ...] | list[str] = ()) -> str:
    """Remove tokens and URL credentials from text destined for logs or errors."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
            text = text.replace(base64.b64encode(secret.encode()).decode(), "***")
    return _URL_CREDS_RE.sub(r"\1***@", text)


def _git(
    args: list[str],
    cwd: str,
    env: dict | None = None,
    secrets: tuple[str, ...] | list[str] = (),
) -> tuple[int, str]:
    # Never let git prompt for credentials (would hang a non-interactive run).
    secrets = tuple(secrets)
    result = run_cmd(
        ["git"] + args,
        cwd,
        timeout=60,
        env=env,
        inherit_env=True,
        git_no_prompt=True,
    )
    if result.error:
        detail = result.error_detail or result.error
        return 1, scrub_secrets(detail, secrets)
    return result.returncode, scrub_secrets((result.stdout + result.stderr).strip(), secrets)


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
        auth_env, secrets = self._auth_env(project)
        target = Path(workspace) / project.id
        target.mkdir(parents=True, exist_ok=True)

        if (target / ".git").exists():
            logger.info(f"Repo already cloned: {target}")
            rc, out = _git(["pull", "--rebase"], str(target), env=auth_env, secrets=secrets)
            if rc != 0:
                logger.warning(f"git pull failed: {out}")
            return str(target)

        logger.info(f"Cloning {repo_url} → {target}")
        rc, out = _git(
            ["clone", "--branch", project.branch, repo_url, str(target)],
            cwd=workspace,
            env=auth_env,
            secrets=secrets,
        )
        if rc != 0:
            raise RuntimeError(f"Clone failed: {out}")

        return str(target)

    @staticmethod
    def _normalize_repo(repo: str) -> str:
        repo = repo.removeprefix("https://").removeprefix("http://")
        return repo.removesuffix(".git")

    def _build_clone_url(self, project: Project) -> str:
        """Clone URL without credentials (auth is injected via the environment)."""
        repo = self._normalize_repo(project.repo)
        if repo.startswith("github.com") or "gitlab" in repo:
            return f"https://{repo}.git"
        return f"https://{repo}"

    def _auth_env(self, project: Project) -> tuple[dict[str, str], tuple[str, ...]]:
        """Build git auth via GIT_CONFIG_* env vars (git >= 2.31).

        The token is sent as an HTTP header for the repo's host only. It never
        appears in the URL, argv, or ``.git/config``. Returns (env, secrets).
        """
        repo = self._normalize_repo(project.repo)
        if repo.startswith("github.com"):
            user, token = "x-access-token", self.cfg.github.token
        elif repo.startswith("gitlab.com") or "gitlab" in repo:
            user, token = "oauth2", self.cfg.gitlab.token
        else:
            return {}, ()
        if not token:
            return {}, ()

        host = repo.split("/", 1)[0]
        basic = base64.b64encode(f"{user}:{token}".encode()).decode()
        env = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.https://{host}/.extraheader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        }
        return env, (token, basic)

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

    def push_branch(
        self,
        project_path: str,
        branch: str,
        remote: str = "origin",
        project: Project | None = None,
    ) -> bool:
        auth_env, secrets = self._auth_env(project) if project else ({}, ())
        rc, out = _git(
            ["push", "--set-upstream", remote, branch],
            cwd=project_path,
            env=auth_env,
            secrets=secrets,
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
            parts = repo_str.replace("github.com/", "").strip("/").removesuffix(".git")
            repo = self._gh.get_repo(parts)
            pr = repo.create_pull(title=title, body=body, head=head, base=base)
            logger.info(f"GitHub PR created: {pr.html_url}")
            return pr.html_url
        except Exception as e:
            logger.error(f"GitHub PR failed: {scrub_secrets(str(e), (self.cfg.github.token,))}")
            return None

    def _open_gitlab_mr(
        self, repo_str: str, head: str, base: str, title: str, body: str
    ) -> str | None:
        try:
            path = repo_str.split("gitlab.com/")[-1].removesuffix(".git")
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
            logger.error(f"GitLab MR failed: {scrub_secrets(str(e), (self.cfg.gitlab.token,))}")
            return None

    # ── Status helpers ────────────────────────────────────────────────────

    def current_branch(self, project_path: str) -> str:
        rc, out = _git(["branch", "--show-current"], cwd=project_path)
        return out if rc == 0 else "unknown"

    def has_changes(self, project_path: str) -> bool:
        rc, out = _git(["status", "--porcelain"], cwd=project_path)
        return rc == 0 and bool(out.strip())
