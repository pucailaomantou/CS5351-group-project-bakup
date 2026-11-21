"""Global-news configured-limit enforcement tests (offline; no network).

Confirmed defect: the model could pass an explicit ``limit`` (observed 30, 50)
that bypassed ``global_news_article_limit`` (10). The fix clamps an explicit
limit to the configured maximum at the vendor layer:

  no limit      -> configured limit
  limit < cap   -> requested limit preserved
  limit >= cap  -> clamped to cap
  (cap unchanged; ticker news untouched)

Additions only; existing frozen tests are not modified.
"""

from __future__ import annotations

from unittest import mock

import pytest

import tradingagents.dataflows.vendors.yahoo.news as news
from tradingagents.dataflows.config import set_config

pytestmark = pytest.mark.unit


class _Search:
    """yfinance Search stub: returns up to ``news_count`` distinct recent articles."""

    def __init__(self, query=None, news_count=None, enable_fuzzy_query=False, **k):
        n = min(news_count or 0, 60)
        self.news = [
            {"content": {"title": f"{query}-{i}", "summary": "s",
                         "provider": {"displayName": "P"}, "canonicalUrl": {"url": "u"},
                         "pubDate": "2026-11-17T00:00:00Z"}}
            for i in range(n)
        ]
        self.quotes = []


def _delivered(out: str) -> int:
    return out.count("### ")


@pytest.fixture(autouse=True)
def _cfg():
    set_config({"global_news_queries": ["qA"], "global_news_article_limit": 10,
                "global_news_lookback_days": 7})


def _run(limit):
    with mock.patch.object(news.yf, "Search", _Search):
        return news.get_global_news_yfinance("2026-11-18", limit=limit)


def test_none_uses_configured_limit():
    assert _delivered(_run(None)) == 10


def test_below_cap_preserved():
    assert _delivered(_run(5)) == 5


def test_equal_cap_preserved():
    assert _delivered(_run(10)) == 10


def test_above_cap_clamped_30():
    assert _delivered(_run(30)) == 10


def test_above_cap_clamped_50():
    assert _delivered(_run(50)) == 10


def test_repeated_calls_each_respect_cap():
    # Every individual call is bounded; the fix is per-call (no run-level counter).
    for lim in (30, 50, 30):
        assert _delivered(_run(lim)) == 10


def test_cap_comes_from_config_not_hardcoded():
    set_config({"global_news_queries": ["qA"], "global_news_article_limit": 3,
                "global_news_lookback_days": 7})
    assert _delivered(_run(None)) == 3
    assert _delivered(_run(99)) == 3      # clamps to the configured cap (3)
    assert _delivered(_run(2)) == 2       # below cap preserved
