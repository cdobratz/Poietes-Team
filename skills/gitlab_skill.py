"""
skills/gitlab_skill.py — GitLab operations skill.

STATUS: placeholder. Every action returns {"success": False, "not_implemented": True}.
Triggers: "gitlab", "merge request", "mr"
"""
from __future__ import annotations

import logging
from typing import Any

from skills.base import Skill, not_implemented

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
    logger.info("create_mr called, but it is not implemented")
    return not_implemented("GitLab create_mr")


def list_mrs(project_id: str, state: str = "opened") -> dict[str, Any]:
    """
    List GitLab merge requests.
    
    Args:
        project_id: GitLab project ID or path
        state: MR state (opened, closed, merged, all)
        
    Returns:
        List of merge requests
    """
    logger.info("list_mrs called, but it is not implemented")
    return not_implemented("GitLab list_mrs")


def _stub_action(feature: str):
    def _run(**_kwargs: Any) -> dict[str, Any]:
        return not_implemented(feature)
    return _run


# Skill definition
skill = Skill(
    name="gitlab",
    description="[STUB, not implemented] GitLab operations including merge requests and projects",
    triggers=["gitlab", "merge request", "mr"],
    action=_stub_action("GitLab skill"),
    agent_scope=None,
    implemented=False,
)

__all__ = ["skill", "create_mr", "list_mrs"]
