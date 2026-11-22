"""Opt-in, read-only capture of news-fetch facts for evidence (Round 2).

The news vendors return only a formatted string, so per-query counts
(requested limit, raw fetched, windowed, deduped/formatted, delivered) are lost
by the time a run record is written. This module lets a runner attach a
collector for the duration of one news tool call and read back those facts
afterward, WITHOUT changing any fetch logic or behaviour:

  * When no collector is active (the default, e.g. normal CLI runs and every
    existing test), every hook is a no-op — the vendor returns exactly what it
    did before.
  * When a collector is active, the vendor appends structured records to it.

Counts are recorded from the real fetch path (inside the per-query loop), never
inferred from an aggregate. Nothing here fetches, retries, or re-queries.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

_active: ContextVar[NewsCapture | None] = ContextVar("news_capture", default=None)


class NewsCapture:
    """Collects per-call news-fetch facts. Thread/async-safe per context."""

    def __init__(self) -> None:
        self.global_queries: list[dict[str, Any]] = []
        self.ticker_calls: list[dict[str, Any]] = []

    def record_global_query(self, record: dict[str, Any]) -> None:
        self.global_queries.append(record)

    def record_ticker_call(self, record: dict[str, Any]) -> None:
        self.ticker_calls.append(record)

    def as_dict(self) -> dict[str, Any]:
        return {
            "global_queries": list(self.global_queries),
            "ticker_calls": list(self.ticker_calls),
        }


@contextlib.contextmanager
def collecting() -> Iterator[NewsCapture]:
    """Activate a fresh collector for the enclosed call; restore prior state after."""
    cap = NewsCapture()
    token = _active.set(cap)
    try:
        yield cap
    finally:
        _active.reset(token)


def active() -> NewsCapture | None:
    """The collector in force for the current context, or ``None`` (observation off)."""
    return _active.get()
