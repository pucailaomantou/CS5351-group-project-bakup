"""Per-run, thread-safe counter for structured-output vs free-text fallback.

The Research Manager, Trader, Portfolio Manager and Sentiment Analyst all try a
structured ``with_structured_output`` call and fall back to plain free text when
it is unavailable or fails (see ``structured.py``). Those four paths never told a
run record *how often* each happened, so a run could not prove whether an agent
answered with structured output or via fallback.

This module adds an opt-in, observation-only recorder. When a run activates it
(the runner wraps its graph run in :func:`collecting`), the shared invocation
helpers bump per-agent and global counters. When no recorder is active — every
CLI run and every existing test — the hooks are no-ops and behaviour is
unchanged. Counters live in a ``ContextVar`` so concurrent agents cannot cross-
count, and each run gets a fresh recorder so nothing leaks between runs.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

_active: ContextVar[StructuredRecorder | None] = ContextVar("structured_recorder", default=None)


class StructuredRecorder:
    """Counts structured attempts / successes / fallbacks per agent and globally."""

    def __init__(self) -> None:
        # agent_name -> {"structured_attempts", "structured_success", "fallback_attempts"}
        self.per_agent: dict[str, dict[str, int]] = {}

    def _bucket(self, agent_name: str) -> dict[str, int]:
        return self.per_agent.setdefault(
            agent_name,
            {"structured_attempts": 0, "structured_success": 0, "fallback_attempts": 0},
        )

    def record_attempt(self, agent_name: str) -> None:
        """A structured binding existed and a structured call is about to run."""
        self._bucket(agent_name)["structured_attempts"] += 1

    def record_success(self, agent_name: str) -> None:
        """The structured call parsed a result; no fallback will run."""
        self._bucket(agent_name)["structured_success"] += 1

    def record_fallback(self, agent_name: str) -> None:
        """The agent will answer in free text (binding absent, or the call failed)."""
        self._bucket(agent_name)["fallback_attempts"] += 1

    def as_dict(self) -> dict:
        totals = {"structured_attempts": 0, "structured_success": 0, "fallback_attempts": 0}
        for bucket in self.per_agent.values():
            for k in totals:
                totals[k] += bucket[k]
        return {"per_agent": {k: dict(v) for k, v in sorted(self.per_agent.items())},
                "totals": totals}


@contextlib.contextmanager
def collecting() -> Iterator[StructuredRecorder]:
    """Activate a fresh recorder for the enclosed run; restore prior state after."""
    rec = StructuredRecorder()
    token = _active.set(rec)
    try:
        yield rec
    finally:
        _active.reset(token)


def active() -> StructuredRecorder | None:
    """The recorder in force for the current context, or ``None`` (observation off)."""
    return _active.get()
