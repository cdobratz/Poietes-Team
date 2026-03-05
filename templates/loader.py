"""
templates/loader.py — Loads and interpolates agent task templates.

Templates are YAML files in the templates/ directory that define
deterministic multi-step agent pipelines.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

TEMPLATES_DIR = Path(__file__).parent

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class TaskStep(BaseModel):
    """A single step in a task template."""
    agent: str
    task: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)


class TaskTemplate(BaseModel):
    """A reusable multi-step agent task template."""
    id: str
    name: str
    description: str = ""
    variables: list[str] = Field(default_factory=list)
    steps: list[TaskStep] = Field(default_factory=list)


def _interpolate_vars(text: str, variables: dict[str, str]) -> str:
    """Replace {{var}} placeholders with provided values."""
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return variables.get(key, m.group(0))
    return _VAR_RE.sub(_replace, text)


def _interpolate_step(step_data: dict, variables: dict[str, str]) -> dict:
    """Interpolate variables in a step's string fields."""
    result = {}
    for key, value in step_data.items():
        if isinstance(value, str):
            result[key] = _interpolate_vars(value, variables)
        elif isinstance(value, list):
            result[key] = [
                _interpolate_vars(v, variables) if isinstance(v, str) else v
                for v in value
            ]
        else:
            result[key] = value
    return result


def load_template(
    template_id: str,
    variables: dict[str, str] | None = None,
) -> TaskTemplate:
    """Load a template by ID and interpolate variables."""
    variables = variables or {}
    path = TEMPLATES_DIR / f"{template_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {template_id}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    # Interpolate variables in each step
    steps_data = raw.get("steps", [])
    interpolated_steps = [_interpolate_step(s, variables) for s in steps_data]
    raw["steps"] = interpolated_steps

    # Also interpolate top-level description
    if "description" in raw and isinstance(raw["description"], str):
        raw["description"] = _interpolate_vars(raw["description"], variables)

    return TaskTemplate.model_validate(raw)


def list_templates() -> list[TaskTemplate]:
    """Discover and return all available templates (without variable interpolation)."""
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
            if raw and "id" in raw and "steps" in raw:
                templates.append(TaskTemplate.model_validate(raw))
        except Exception:
            continue
    return templates
