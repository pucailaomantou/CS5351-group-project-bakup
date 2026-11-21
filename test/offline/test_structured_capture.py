"""Round 2 structured/fallback counting tests (offline; no provider, no network).

Verifies the unified recorder in ``structured_capture``: per-agent + global
attempts/success/fallback, RM/Trader/PM coverage, concurrent isolation, and no
cross-run residue. Also exercises the real agent helpers where practical.
"""

from __future__ import annotations

import threading
from unittest import mock

import pytest

from tradingagents.agents import structured_capture
from tradingagents.agents.structured import invoke_structured

pytestmark = pytest.mark.unit


def _ok_llm(value="OK"):
    llm = mock.MagicMock()
    llm.invoke.return_value = value
    return llm


def _raise_llm():
    llm = mock.MagicMock()
    llm.invoke.side_effect = RuntimeError("provider boom")
    return llm


def test_structured_success_counts():
    with structured_capture.collecting() as rec:
        assert invoke_structured(_ok_llm("X"), "p", "Research Manager") == "X"
    d = rec.as_dict()
    assert d["per_agent"]["Research Manager"] == {
        "structured_attempts": 1, "structured_success": 1, "fallback_attempts": 0}
    assert d["totals"] == {"structured_attempts": 1, "structured_success": 1, "fallback_attempts": 0}


def test_structured_fail_then_fallback_counts():
    with structured_capture.collecting() as rec:
        assert invoke_structured(_raise_llm(), "p", "Trader") is None
    d = rec.as_dict()["per_agent"]["Trader"]
    assert d == {"structured_attempts": 1, "structured_success": 0, "fallback_attempts": 1}


def test_no_binding_counts_as_fallback_only():
    with structured_capture.collecting() as rec:
        assert invoke_structured(None, "p", "Portfolio Manager") is None
    d = rec.as_dict()["per_agent"]["Portfolio Manager"]
    assert d == {"structured_attempts": 0, "structured_success": 0, "fallback_attempts": 1}


def test_none_result_is_fallback_not_success():
    # A parser that returns None (thinking model answered in prose) is a miss.
    llm = mock.MagicMock()
    llm.invoke.return_value = None
    with structured_capture.collecting() as rec:
        assert invoke_structured(llm, "p", "Portfolio Manager") is None
    d = rec.as_dict()["per_agent"]["Portfolio Manager"]
    assert d["structured_success"] == 0 and d["fallback_attempts"] == 1


def test_rm_trader_pm_all_counted():
    with structured_capture.collecting() as rec:
        invoke_structured(_ok_llm(), "p", "Research Manager")
        invoke_structured(_raise_llm(), "p", "Trader")
        invoke_structured(None, "p", "Portfolio Manager")
    d = rec.as_dict()
    assert set(d["per_agent"]) == {"Research Manager", "Trader", "Portfolio Manager"}
    assert d["totals"] == {"structured_attempts": 2, "structured_success": 1, "fallback_attempts": 2}


def test_concurrent_agents_do_not_cross_count():
    # Two threads, each its own collecting() context, must not mix counts.
    results: dict[str, dict] = {}

    def worker(tag, succeed):
        with structured_capture.collecting() as rec:
            llm = _ok_llm() if succeed else _raise_llm()
            for _ in range(5):
                invoke_structured(llm, "p", "Research Manager")
            results[tag] = rec.as_dict()

    t1 = threading.Thread(target=worker, args=("a", True))
    t2 = threading.Thread(target=worker, args=("b", False))
    t1.start(); t2.start(); t1.join(); t2.join()
    # ContextVar is per-thread context: each thread saw only its own 5 calls.
    assert results["a"]["totals"] == {"structured_attempts": 5, "structured_success": 5, "fallback_attempts": 0}
    assert results["b"]["totals"] == {"structured_attempts": 5, "structured_success": 0, "fallback_attempts": 5}


def test_no_residue_between_runs():
    with structured_capture.collecting() as rec1:
        invoke_structured(_ok_llm(), "p", "Trader")
    with structured_capture.collecting() as rec2:
        invoke_structured(_raise_llm(), "p", "PM")  # different agent name on purpose
    assert rec1.as_dict()["totals"]["structured_success"] == 1
    assert rec2.as_dict()["totals"] == {"structured_attempts": 1, "structured_success": 0, "fallback_attempts": 1}
    assert "Trader" not in rec2.as_dict()["per_agent"]  # run 1's traffic not in run 2


def test_inactive_recorder_is_noop():
    # No collecting() active: invoke_structured behaves normally, no recorder.
    assert structured_capture.active() is None
    assert invoke_structured(_ok_llm("Z"), "p", "Trader") == "Z"
    assert structured_capture.active() is None
