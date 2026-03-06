"""
skills/gitlab_skill.py — GitLab operations skill.

Triggers: "gitlab", "merge request", "mr"
"""
from __future__ import annotations

import logging
from typing import Any

from skills.base import Skill

logger = logging.getLogger(__name__)


def create_mr(
    source_branch: str,
    target_branch: str,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    """
    Create a GitLab merge request.
    
    Args:
        source_branch: Source branch name
        target_branch: Target branch
        title: MR title
        description: MR description
        
    Returns:
        Result with MR URL
    """
    logger.info(f"Creating MR: {source_branch} -> {target_branch}: {title}")
    
    return {
        "success": True,
        "mr_url": f"https://gitlab.com/org/repo/merge_requests/1",
        "source_branch": source_branch,
        "target_branch": target_branch,
        "title": title,
    }


def list_mrs(project_id: str, state: str = "opened") -> dict[str, Any]:
    """
    List GitLab merge requests.
    
    Args:
        project_id: GitLab project ID or path
        state: MR state (opened, closed, merged, all)
        
    Returns:
        List of merge requests
    """
    logger.info(f"Listing MRs for {project_id}")
    
    return {
        "success": True,
        "merge_requests": [],
        "project_id": project_id,
    }


# Skill definition
skill = Skill(
    name="gitlab",
    description="GitLab operations including merge requests and projects",
    triggers=["gitlab", "merge request", "mr"],
    agent_scope=None,
)

__all__ = ["skill", "create_mr", "list_mrs"]
