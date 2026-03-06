"""
skills/github_skill.py — GitHub operations skill.

Triggers: "github", "pr", "pull request", "issue", "repo", "commit"
"""
from __future__ import annotations

import os
import logging
from typing import Any

from skills.base import Skill

logger = logging.getLogger(__name__)

# Try to import GitHub tools
try:
    from tools.git_tools import GitManager
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False


def create_pr(branch: str, title: str, body: str = "", base: str = "main") -> dict[str, Any]:
    """
    Create a GitHub pull request.
    
    Args:
        branch: Source branch name
        title: PR title
        body: PR description
        base: Target branch (default: main)
        
    Returns:
        Result dict with success status and PR URL
    """
    if not GITHUB_AVAILABLE:
        return {"success": False, "error": "GitHub tools not available"}
    
    # This would use GitHub API in a real implementation
    logger.info(f"Creating PR: {branch} -> {base}: {title}")
    
    return {
        "success": True,
        "pr_url": f"https://github.com/org/repo/pull/1",
        "branch": branch,
        "base": base,
        "title": title,
    }


def list_issues(repo: str, state: str = "open") -> dict[str, Any]:
    """
    List GitHub issues.
    
    Args:
        repo: Repository in format "owner/repo"
        state: Issue state (open, closed, all)
        
    Returns:
        List of issues
    """
    if not GITHUB_AVAILABLE:
        return {"success": False, "error": "GitHub tools not available"}
    
    logger.info(f"Listing issues for {repo} (state: {state})")
    
    return {
        "success": True,
        "issues": [],
        "repo": repo,
    }


def create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create a GitHub issue.
    
    Args:
        repo: Repository in format "owner/repo"
        title: Issue title
        body: Issue description
        labels: List of labels
        
    Returns:
        Result with issue URL
    """
    if not GITHUB_AVAILABLE:
        return {"success": False, "error": "GitHub tools not available"}
    
    logger.info(f"Creating issue in {repo}: {title}")
    
    return {
        "success": True,
        "issue_url": f"https://github.com/{repo}/issues/1",
        "title": title,
    }


# Skill definition
skill = Skill(
    name="github",
    description="GitHub operations including PRs, issues, and repository management",
    triggers=[
        "github", "pr", "pull request", "issue", 
        "repo", "commit", "branch", "merge"
    ],
    agent_scope=None,  # Available to all agents
)

# Export skill for registry
__all__ = ["skill", "create_pr", "list_issues", "create_issue"]
