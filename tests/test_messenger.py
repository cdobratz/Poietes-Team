"""Telegram: sender allowlist and concurrency cap (no network)."""
from __future__ import annotations

import threading

import pytest

pytest.importorskip("telegram")

from messaging.messenger import TelegramMessenger  # noqa: E402


def _m(on_command=None, **kw) -> TelegramMessenger:
    return TelegramMessenger("123:abc", "111", on_command=on_command, **kw)


def test_allowlist_is_chat_id_plus_extras():
    m = _m(allowed_chat_ids=["222"])
    assert m.is_authorized(111) and m.is_authorized("222")
    assert not m.is_authorized(333)


def test_empty_chat_id_authorizes_nobody():
    m = TelegramMessenger("123:abc", "", on_command=lambda t: None)
    assert not m.is_authorized(0) and not m.is_authorized("")


def test_concurrency_cap_refuses_extra_runs():
    gate, started = threading.Event(), threading.Event()
    calls: list[str] = []

    def on_command(task: str):
        calls.append(task)
        started.set()
        gate.wait(5)

    m = _m(on_command, max_concurrent_runs=1)
    assert m.try_start_run("one") is True
    assert started.wait(2)
    assert m.try_start_run("two") is False      # cap reached
    gate.set()
    for _ in range(100):                          # slot is released afterwards
        if m.try_start_run("three"):
            break
        threading.Event().wait(0.05)
    else:
        pytest.fail("slot never released")
    assert calls[0] == "one" and "two" not in calls


def test_failing_run_releases_slot():
    done = threading.Event()

    def boom(task: str):
        done.set()
        raise RuntimeError("x")

    m = _m(boom, max_concurrent_runs=1)
    assert m.try_start_run("t")
    assert done.wait(2)
    for _ in range(100):
        if m.try_start_run("t2"):
            return
        threading.Event().wait(0.05)
    pytest.fail("slot leaked after exception")
