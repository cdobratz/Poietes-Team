"""
skills/debug_skill.py — Debugging helpers skill.

Triggers: "debug", "trace", "log", "error", "exception", "stack"
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

from skills.base import Skill

logger = logging.getLogger(__name__)


def analyze_error(error_message: str, stack_trace: str = "") -> dict[str, Any]:
    """
    Analyze an error and provide debugging suggestions.
    
    Args:
        error_message: The error message
        stack_trace: Optional stack trace
        
    Returns:
        Analysis with suggestions
    """
    suggestions = []
    
    # Common error patterns and suggestions
    patterns = {
        "import": "Check if the module is installed. Try: pip install <module>",
        "module not found": "Install missing module or check PYTHONPATH",
        "permission denied": "Check file/directory permissions",
        "connection refused": "Ensure the service is running",
        "timeout": "Check network or increase timeout value",
        "null": "Check for None values before accessing attributes",
        "undefined": "Check variable initialization",
        "syntax": "Review Python syntax, check for typos",
        "indentation": "Check whitespace/indentation",
    }
    
    error_lower = error_message.lower()
    for pattern, suggestion in patterns.items():
        if pattern in error_lower:
            suggestions.append(suggestion)
    
    if not suggestions:
        suggestions.append("Review the error message and stack trace for clues")
    
    return {
        "success": True,
        "error": error_message,
        "suggestions": suggestions,
        "stack_trace": stack_trace[:500] if stack_trace else None,
    }


def format_exception(exc: Exception) -> dict[str, Any]:
    """
    Format an exception for display.
    
    Args:
        exc: Exception object
        
    Returns:
        Formatted exception details
    """
    return {
        "success": True,
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }


def check_logs(log_pattern: str, lines: int = 50) -> dict[str, Any]:
    """
    Check recent log entries matching a pattern.
    
    Args:
        log_pattern: Pattern to search for in logs
        lines: Number of lines to retrieve
        
    Returns:
        Log entries
    """
    # This would read actual log files in a real implementation
    return {
        "success": True,
        "pattern": log_pattern,
        "entries": [
            f"Sample log entry {i} matching {log_pattern}"
            for i in range(min(5, lines))
        ],
    }


# Skill definition
skill = Skill(
    name="debug",
    description="Debugging helpers: error analysis, traceback formatting, log checking",
    triggers=["debug", "trace", "log", "error", "exception", "stack", "fix"],
    agent_scope=None,
)

__all__ = ["skill", "analyze_error", "format_exception", "check_logs"]
