"""Config loading: loud failure on unset vars, ${VAR:-default}, strict models."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from config.loader import ConfigError, Project, _interpolate, load_projects, load_settings

ROOT = Path(__file__).resolve().parent.parent


def test_unset_var_raises_and_lists_all(monkeypatch):
    monkeypatch.delenv("A_UNSET", raising=False)
    monkeypatch.delenv("B_UNSET", raising=False)
    with pytest.raises(ConfigError) as e:
        _interpolate({"x": "${A_UNSET}", "y": ["${B_UNSET}"]})
    assert "A_UNSET" in str(e.value) and "B_UNSET" in str(e.value)


def test_empty_var_counts_as_unset(monkeypatch):
    monkeypatch.setenv("EMPTY_V", "")
    with pytest.raises(ConfigError):
        _interpolate("${EMPTY_V}")


def test_default_and_set_values(monkeypatch):
    monkeypatch.delenv("D_UNSET", raising=False)
    monkeypatch.setenv("D_SET", "real")
    assert _interpolate("${D_UNSET:-fallback}") == "fallback"
    assert _interpolate("${D_UNSET:-}") == ""
    assert _interpolate("${D_SET:-fallback}") == "real"
    assert _interpolate("pre-${D_SET}-post") == "pre-real-post"


def test_non_strict_blanks_unset(monkeypatch):
    monkeypatch.delenv("N_UNSET", raising=False)
    assert _interpolate("${N_UNSET}", strict=False) == ""


def test_unknown_keys_rejected():
    with pytest.raises(ValidationError):
        Project(id="x", name="x", bogus=1)


def test_unknown_key_in_settings_file_rejected(tmp_path, monkeypatch):
    p = tmp_path / "settings.yaml"
    p.write_text("workspace:\n  aproval_required: false\n")
    with pytest.raises(ValidationError):
        load_settings(p)


def test_settings_file_with_unset_var_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("SOME_UNSET_KEY", raising=False)
    p = tmp_path / "settings.yaml"
    p.write_text("messaging:\n  telegram:\n    bot_token: ${SOME_UNSET_KEY}\n")
    with pytest.raises(ConfigError):
        load_settings(p)


def test_example_config_loads_with_only_required_key(monkeypatch):
    for v in ("XAI_API_KEY", "MINIMAX_API_KEY", "MEM0_API_KEY", "TELEGRAM_BOT_TOKEN",
              "TELEGRAM_CHAT_ID", "GITHUB_TOKEN", "GITLAB_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    s = load_settings(ROOT / "config" / "settings.example.yaml")
    assert s.messaging.telegram.max_concurrent_runs >= 1
    assert s.messaging.telegram.allowed_chat_ids == []
    assert load_projects(ROOT / "config" / "projects.example.yaml").projects
