"""
skills/base.py — Base framework for skill definition and registry.

Provides:
- Skill dataclass: name, description, triggers[], action()
- SkillRegistry: register(), find_by_trigger(), list_all()
"""
from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Type alias for skill action functions
SkillAction = Callable[..., dict[str, Any]]


@dataclass
class Skill:
    """
    A skill that can be loaded by agents.
    
    Attributes:
        name: Unique identifier for the skill
        description: Human-readable description of what the skill does
        triggers: List of keywords that activate this skill
        action: Function that executes the skill
        agent_scope: Which agents can use this skill (None = all)
    """
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    action: SkillAction | None = None
    agent_scope: list[str] | None = None
    
    def matches_trigger(self, text: str) -> bool:
        """Check if the given text matches any of this skill's triggers."""
        text_lower = text.lower()
        return any(
            trigger.lower() in text_lower 
            for trigger in self.triggers
        )
    
    def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the skill's action function."""
        if self.action is None:
            return {"success": False, "error": "No action defined"}
        try:
            return self.action(**kwargs)
        except Exception as e:
            logger.exception(f"Skill '{self.name}' execution failed")
            return {"success": False, "error": str(e)}


class SkillRegistry:
    """
    Registry for managing skills.
    
    Supports:
    - Registering skills manually
    - Auto-loading skills from Python files in skills/ directory
    - Finding skills by trigger keywords
    - Listing all available skills
    """
    
    def __init__(self):
        self._skills: dict[str, Skill] = {}
    
    def register(self, skill: Skill) -> None:
        """Register a skill in the registry."""
        if skill.name in self._skills:
            logger.warning(f"Skill '{skill.name}' already registered, overwriting")
        self._skills[skill.name] = skill
        logger.info(f"Registered skill: {skill.name}")
    
    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)
    
    def find_by_trigger(self, text: str, agent_name: str | None = None) -> list[Skill]:
        """
        Find all skills matching the given text triggers.
        
        Args:
            text: Input text to match against triggers
            agent_name: Optional agent to filter skills by
            
        Returns:
            List of matching skills
        """
        matches = []
        for skill in self._skills.values():
            # Filter by agent scope if specified
            if agent_name and skill.agent_scope:
                if agent_name not in skill.agent_scope:
                    continue
            
            if skill.matches_trigger(text):
                matches.append(skill)
        
        return matches
    
    def list_all(self, agent_name: str | None = None) -> list[Skill]:
        """List all registered skills, optionally filtered by agent."""
        skills = list(self._skills.values())
        
        if agent_name:
            skills = [
                s for s in skills 
                if s.agent_scope is None or agent_name in s.agent_scope
            ]
        
        return skills
    
    def load_from_directory(self, directory: str) -> int:
        """
        Auto-load skills from Python files in a directory.
        
        Looks for modules that export a 'skill' or 'get_skill' attribute.
        
        Args:
            directory: Path to skills directory
            
        Returns:
            Number of skills loaded
        """
        skills_dir = Path(directory)
        if not skills_dir.exists():
            logger.warning(f"Skills directory not found: {directory}")
            return 0
        
        loaded = 0
        for file_path in skills_dir.glob("*.py"):
            if file_path.name.startswith("_"):
                continue
            
            try:
                # Import the module
                module_name = file_path.stem
                
                # Add directory to path if not already there
                parent_dir = str(skills_dir.parent)
                if parent_dir not in sys.path:
                    sys.path.insert(0, parent_dir)
                
                module = importlib.import_module(f"{skills_dir.name}.{module_name}")
                
                # Look for skill exports
                if hasattr(module, "skill"):
                    skill = module.skill
                    if isinstance(skill, Skill):
                        self.register(skill)
                        loaded += 1
                
                if hasattr(module, "get_skill"):
                    skill = module.get_skill()
                    if isinstance(skill, Skill):
                        self.register(skill)
                        loaded += 1
                        
                # Look for skills list
                if hasattr(module, "skills"):
                    skills_list = module.skills
                    if isinstance(skills_list, list):
                        for s in skills_list:
                            if isinstance(s, Skill):
                                self.register(s)
                                loaded += 1
                                
            except Exception as e:
                logger.warning(f"Failed to load skill from {file_path}: {e}")
        
        return loaded


# Global registry instance
_global_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Get the global skill registry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry()
    return _global_registry


def init_skill_registry(skills_dir: str | None = None) -> SkillRegistry:
    """
    Initialize the global skill registry.
    
    Args:
        skills_dir: Optional path to skills directory to auto-load
        
    Returns:
        Initialized SkillRegistry
    """
    global _global_registry
    _global_registry = SkillRegistry()
    
    if skills_dir:
        _global_registry.load_from_directory(skills_dir)
    
    return _global_registry


# Import sys for path manipulation in load_from_directory
import sys
