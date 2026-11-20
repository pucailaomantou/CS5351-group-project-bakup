"""Global-news fetch-vs-deliver separation tests (offline; no network).

The provider only serves the newest articles, so a small fetch size can miss the
as_of window. The fix fetches a bounded deeper candidate pool (>=50) per query,
filters by window and de-dupes, then delivers at most ``delivered_limit`` (=the
configured cap, and never above it). These tests pin that behaviour and that the
LLM-facing delivered count stays within the cap.

After-only additions; existing frozen tests are not modified. The scenarios are
built from mock article lists shaped like real fixtures (no Yahoo call).
"""

from __future__ import annotations

from unittest import mock

import pytest

import tradingagents.dataflows.vendors.yahoo.news as news
from tradingagents.dataflows.config import set_config

pytestmark = pytest.mark.unit


def _art(query, i, date):
    return {"content": {
        "title": f"{query}-{i}", "summary": "s", "provider": {"displayName": "P"},
        "canonicalUrl": {"url": "u"}, "pubDate": f"{date}T12:00:00Z",
    }}


class _Search:
    """Returns `articles` (a fixed list) regardless of news_count, so a test can
    place out-of-window items first and in-window items deeper in the pool."""

    def __init__(self, articles):
        self._articles = articles

    def __call__(self, query=None, news_count=None, enable_fuzzy_query=False, **k):
        s = type("S", (), {})()
        s.news = list(self._articles)
        s.quotes = []
        return s


@pytest.fixture(autouse=True)
def _cfg():
    set_config({"global_news_queries": ["qA"], "global_news_article_limit": 10,
                "global_news_lookback_days": 7})


def _run(articles, limit=None):
    with mock.patch.object(news.yf, "Search", _Search(articles)):
        return news.get_global_news_yfinance("2026-11-18", limit=limit)


def _delivered(out):
    return out.count("### ")


def test_first10_out_of_window_deeper_in_window_still_delivers():
    # Newest 10 are AFTER the window (2026-11-19); next 30 are inside (11-18).
    arts = [_art("qA", i, "2026-11-19") for i in range(10)] + \
           [_art("qA", 10 + i, "2026-11-18") for i in range(30)]
    out = _run(arts)
    assert 0 < _delivered(out) <= 10
    assert "2026-11-19" not in out          # no future/out-of-window leak


def test_all_out_of_window_reports_unavailable_no_leak():
    arts = [_art("qA", i, "2026-11-19") for i in range(40)]  # all after as_of
    out = _run(arts)
    assert _delivered(out) == 0
    assert "only serves recent items" in out or "No global news" in out


def test_future_articles_filtered_not_leaked():
    # Mix: some future (11-20), some in window (11-18)
    arts = [_art("qA", i, "2026-11-20") for i in range(5)] + \
           [_art("qA", 5 + i, "2026-11-18") for i in range(20)]
    out = _run(arts)
    assert "2026-11-20" not in out
    assert 0 < _delivered(out) <= 10


def test_cross_query_dedupe():
    # Same titles repeated across two queries -> de-duped before delivery.
    set_config({"global_news_queries": ["qA", "qB"], "global_news_article_limit": 10,
                "global_news_lookback_days": 7})
    a = [_art("same", i, "2026-11-18") for i in range(6)]
    b = [_art("same", i, "2026-11-18") for i in range(6)]  # identical titles
    with mock.patch.object(news.yf, "Search", _Search(a)):
        out_a = news.get_global_news_yfinance("2026-11-18")
    # delivered unique titles only (<=6), independent of duplicate query
    assert _delivered(out_a) == 6


def test_small_explicit_limit_delivers_at_most_that():
    arts = [_art("qA", i, "2026-11-18") for i in range(40)]
    out = _run(arts, limit=5)
    assert _delivered(out) <= 5


def test_large_explicit_limit_clamped_to_config_cap():
    arts = [_art("qA", i, "2026-11-18") for i in range(80)]
    out = _run(arts, limit=30)          # > cap(10)
    assert _delivered(out) <= 10


def test_bounded_single_search_per_query():
    # Exactly one Search call per configured query (no pagination).
    calls = {"n": 0}
    base = _Search([_art("qA", i, "2026-11-18") for i in range(5)])

    def counting(*a, **k):
        calls["n"] += 1
        return base(*a, **k)

    set_config({"global_news_queries": ["qA", "qB"], "global_news_article_limit": 50,
                "global_news_lookback_days": 7})
    with mock.patch.object(news.yf, "Search", counting):
        news.get_global_news_yfinance("2026-11-18")
    assert calls["n"] == 2   # one per query, no pagination
