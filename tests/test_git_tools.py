"""Git auth must never put tokens in URLs/argv, and errors/logs must be scrubbed."""
from __future__ import annotations

import base64

from config.loader import GitConfig, GitHubConfig, GitLabConfig, Project
from tools.git_tools import GitManager, _git, scrub_secrets

TOKEN = "ghp_SECRET123456"


def _mgr() -> GitManager:
    return GitManager(GitConfig(
        github=GitHubConfig(enabled=False, token=TOKEN),
        gitlab=GitLabConfig(enabled=False, token="glpat-SECRET"),
    ))


def test_clone_url_has_no_credentials():
    p = Project(id="x", name="x", repo="github.com/org/repo")
    url = _mgr()._build_clone_url(p)
    assert url == "https://github.com/org/repo.git"
    assert TOKEN not in url


def test_clone_url_handles_dot_git_suffix_and_scheme():
    p = Project(id="x", name="x", repo="https://github.com/org/gitrepo.git")
    assert _mgr()._build_clone_url(p) == "https://github.com/org/gitrepo.git"


def test_auth_env_uses_extraheader_for_host_only():
    p = Project(id="x", name="x", repo="github.com/org/repo")
    env, secrets = _mgr()._auth_env(p)
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    basic = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {basic}"
    assert TOKEN in secrets and basic in secrets


def test_auth_env_empty_without_token_or_unknown_host():
    m = GitManager(GitConfig())
    assert m._auth_env(Project(id="x", name="x", repo="github.com/o/r")) == ({}, ())
    assert _mgr()._auth_env(Project(id="x", name="x", repo="example.com/o/r")) == ({}, ())


def test_scrub_secrets():
    basic = base64.b64encode(f"u:{TOKEN}".encode()).decode()
    text = f"fatal: {TOKEN} {basic} https://oauth2:abc@gitlab.com/o/r.git"
    out = scrub_secrets(text, (TOKEN, basic))
    assert TOKEN not in out and basic not in out and "abc" not in out


def test_git_errors_are_scrubbed(tmp_path):
    # Clone from a bogus local path whose name contains the secret: git echoes it back.
    rc, out = _git(["clone", f"/nonexistent/{TOKEN}", str(tmp_path / "t")],
                   cwd=str(tmp_path), secrets=(TOKEN,))
    assert rc != 0
    assert TOKEN not in out
