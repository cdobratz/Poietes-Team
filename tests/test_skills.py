"""Placeholder skills must say so, never fake success."""
from __future__ import annotations

import pytest

import skills.debug_skill as debug
import skills.deploy_skill as deploy
import skills.github_skill as gh
import skills.gitlab_skill as gl


@pytest.mark.parametrize("call", [
    lambda: gh.create_pr("b", "t"),
    lambda: gh.list_issues("o/r"),
    lambda: gh.create_issue("o/r", "t"),
    lambda: gl.create_mr("a", "b", "t"),
    lambda: gl.list_mrs("1"),
    lambda: deploy.deploy_docker("img"),
    lambda: deploy.deploy_k8s("m"),
    lambda: deploy.build_image(".", "t"),
    lambda: deploy.rollback("d"),
    lambda: debug.check_logs("x"),
])
def test_stubs_return_not_implemented(call):
    r = call()
    assert r["success"] is False and r["not_implemented"] is True
    assert "pr_url" not in r and "issue_url" not in r and "mr_url" not in r


def test_real_debug_helpers_still_work():
    assert debug.analyze_error("ConnectionError: timeout")["success"] is True
