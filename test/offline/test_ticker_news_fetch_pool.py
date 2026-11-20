"""Ticker-news fetch-vs-deliver separation tests (offline; no network).

The Yahoo ticker feed returns only the newest N articles. With fetch==deliver==8,
a run whose newest 8 are all after ``as_of`` (e.g. 2026-11-19 for an 11-18 run)
loses the in-window articles (as_of 11-18) entirely -> news_recency_window. The
fix fetches a bounded deeper pool, date-filters + de-dupes, then delivers at most
``news_article_limit`` (8). These pin that behaviour, the no-future-leak rule, and
the recorded counts.

After-only additions; existing frozen tests are not modified.
"""

from __future__ import annotations

from unittest import mock

import pytest

import tradingagents.dataflows.vendors.yahoo.news as news
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.vendors.yahoo import news_capture

pytestmark = pytest.mark.unit


def _art(i, date, title=None):
    return {"content": {
        "title": title or f"t-{i}", "summary": "s", "provider": {"displayName": "P"},
        "canonicalUrl": {"url": "u"}, "pubDate": f"{date}T12:00:00Z",
    }}


class _Ticker:
    """Feed = fixed list; records the count it was asked for."""
    last_count = None

    def __init__(self, symbol):
        pass

    def get_news(self, count=None):
        _Ticker.last_count = count
        return list(_FEED)


_FEED: list = []


@pytest.fixture(autouse=True)
def _cfg():
    set_config({"news_article_limit": 8, "global_news_article_limit": 10,
                "global_news_queries": ["q"], "global_news_lookback_days": 7})


def _run(feed):
    global _FEED
    _FEED = feed
    with mock.patch.object(news.yf, "Ticker", _Ticker):
        return news.get_news_yfinance("NVDA", "2026-11-11", "2026-11-18")


class _Search:
    """Yahoo search stub: returns the tagged articles it was configured with."""

    def __init__(self, news=()):
        self._news = list(news)

    def __call__(self, query, news_count=None, enable_fuzzy_query=False):
        obj = mock.Mock()
        obj.news = list(self._news)
        obj.quotes = [{"symbol": "NVDA"}]
        return obj


def _run_with_search(feed, search_news):
    global _FEED
    _FEED = feed
    tagged = [dict(a, relatedTickers=["NVDA"]) for a in search_news]
    with mock.patch.object(news.yf, "Ticker", _Ticker), \
            mock.patch.object(news.yf, "Search", _Search(tagged)):
        return news.get_news_yfinance("NVDA", "2026-11-11", "2026-11-18")


def test_recent8_future_but_deeper_in_window_delivers():
    # Newest 8 dated 2026-11-19 (after as_of); next 20 dated 2026-11-18 (in window)
    feed = [_art(i, "2026-11-19") for i in range(8)] + \
           [_art(100 + i, "2026-11-18") for i in range(20)]
    out = _run(feed)
    assert 0 < out.count("### ") <= 8
    assert "2026-11-19" not in out          # no future leak


def test_all_future_reports_unavailable():
    feed = [_art(i, "2026-11-19") for i in range(40)]
    out = _run(feed)
    assert out.count("### ") == 0
    assert "only serves recent items" in out or "No news found" in out


def test_deliver_capped_at_news_article_limit():
    feed = [_art(i, "2026-11-18") for i in range(60)]
    out = _run(feed)
    assert out.count("### ") == 8          # capped at config 8, not 60


def test_fetch_pool_deeper_than_deliver_limit():
    feed = [_art(i, "2026-11-18") for i in range(60)]
    _run(feed)
    assert _Ticker.last_count is not None and _Ticker.last_count >= 50  # fetched pool > 8


def test_duplicate_titles_deduped():
    feed = [_art(0, "2026-11-18", title="same"), _art(1, "2026-11-18", title="same"),
            _art(2, "2026-11-18", title="other")]
    out = _run(feed)
    assert out.count("### ") == 2          # 'same' collapsed, 'other' kept


def test_capture_counts_fetch_vs_deliver():
    feed = [_art(i, "2026-11-19") for i in range(8)] + [_art(50 + i, "2026-11-18") for i in range(20)]
    with news_capture.collecting() as cap:
        _run(feed)
    rec = cap.ticker_calls[0]
    assert rec["requested_limit"] >= 50 and rec["delivered_limit"] == 8
    assert rec["fetched_count"] == 28 and rec["windowed_count"] == 20
    assert rec["delivered_count"] <= 8


# --- search supplement when the bounded feed yields nothing in the window -----
# The real 2026-11-18 After failure: the newest 50 quote-feed items were all
# 2026-11-19, so windowed_count=0 and the recency-gap notice was returned even
# though Yahoo search *had* 2026-11-18 articles. The fix consults search as a
# supplement (not only when the feed is empty) before declaring the gap.


def test_all_future_feed_supplemented_by_search_in_window():
    feed = [_art(i, "2026-11-19") for i in range(50)]        # all after as_of
    search = [_art(200 + i, "2026-11-18") for i in range(6)]  # search reaches as_of
    out = _run_with_search(feed, search)
    assert 0 < out.count("### ") <= 8
    assert "2026-11-19" not in out              # still no future leak
    assert "only serves recent items" not in out


def test_search_supplement_reports_counts_and_fallback():
    feed = [_art(i, "2026-11-19") for i in range(50)]
    search = [_art(200 + i, "2026-11-18") for i in range(3)]
    with news_capture.collecting() as cap:
        _run_with_search(feed, search)
    rec = cap.ticker_calls[0]
    assert rec["feed_nonempty"] is True
    assert rec["used_search_fallback"] is True
    assert rec["fetched_count"] == 53           # 50 feed + 3 search candidates
    assert rec["windowed_count"] == 3
    assert rec["delivered_count"] == 3


def test_all_future_feed_and_empty_search_reports_gap():
    feed = [_art(i, "2026-11-19") for i in range(50)]
    out = _run_with_search(feed, [])
    assert out.count("### ") == 0
    assert "only serves recent items" in out or "No news found" in out


def test_feed_in_window_does_not_consult_search():
    feed = [_art(i, "2026-11-18") for i in range(10)]
    search = [_art(200 + i, "2026-11-18") for i in range(6)]
    with news_capture.collecting() as cap:
        out = _run_with_search(feed, search)
    rec = cap.ticker_calls[0]
    assert out.count("### ") == 8               # deliver cap honoured
    assert rec["used_search_fallback"] is False
    assert rec["fetched_count"] == 10           # search not pooled
