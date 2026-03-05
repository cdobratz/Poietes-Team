"""Tests for the agent task template system."""
from __future__ import annotations

import pytest

from templates.loader import (
    TaskTemplate,
    TaskStep,
    list_templates,
    load_template,
    _interpolate_vars,
)


class TestInterpolation:
    def test_basic_interpolation(self):
        result = _interpolate_vars("Hello {{name}}", {"name": "world"})
        assert result == "Hello world"

    def test_multiple_vars(self):
        result = _interpolate_vars(
            "{{agent}} runs on {{project}}",
            {"agent": "monitor", "project": "myapp"},
        )
        assert result == "monitor runs on myapp"

    def test_missing_var_kept(self):
        result = _interpolate_vars("Hello {{missing}}", {})
        assert result == "Hello {{missing}}"

    def test_no_vars(self):
        result = _interpolate_vars("plain text", {"unused": "val"})
        assert result == "plain text"


class TestLoadTemplate:
    def test_load_full_audit(self):
        template = load_template("full_audit", {"project": "myapp"})
        assert template.id == "full_audit"
        assert template.name == "Full Project Audit"
        assert len(template.steps) == 3
        assert template.steps[0].agent == "monitor"
        # Check variable interpolation in step task
        assert "myapp" in template.steps[0].task

    def test_load_implement_feature(self):
        template = load_template(
            "implement_feature",
            {"project": "api", "feature": "auth"},
        )
        assert template.id == "implement_feature"
        assert len(template.steps) == 4
        assert "auth" in template.steps[1].task
        assert "api" in template.steps[1].task

    def test_load_security_fix(self):
        template = load_template("security_fix", {"project": "web"})
        assert template.id == "security_fix"
        assert len(template.steps) == 3
        # First and last steps should be security agent
        assert template.steps[0].agent == "security"
        assert template.steps[2].agent == "security"

    def test_load_onboard_project(self):
        template = load_template("onboard_project", {"project": "newapp"})
        assert template.id == "onboard_project"
        assert len(template.steps) == 3

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError, match="Template not found"):
            load_template("does_not_exist")

    def test_load_without_variables(self):
        template = load_template("full_audit")
        assert template.id == "full_audit"
        # Variables should remain as {{project}} placeholders
        assert "{{project}}" in template.steps[0].task


class TestListTemplates:
    def test_list_returns_templates(self):
        templates = list_templates()
        assert len(templates) >= 4
        ids = {t.id for t in templates}
        assert "full_audit" in ids
        assert "implement_feature" in ids
        assert "security_fix" in ids
        assert "onboard_project" in ids

    def test_templates_have_steps(self):
        for template in list_templates():
            assert len(template.steps) > 0
            for step in template.steps:
                assert step.agent in ("monitor", "coder", "security", "content")
                assert step.task


class TestModels:
    def test_task_step_defaults(self):
        step = TaskStep(agent="monitor", task="scan")
        assert step.description == ""
        assert step.depends_on == []

    def test_task_template_defaults(self):
        template = TaskTemplate(id="test", name="Test")
        assert template.description == ""
        assert template.variables == []
        assert template.steps == []
