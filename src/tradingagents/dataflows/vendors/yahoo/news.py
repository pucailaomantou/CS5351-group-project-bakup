"""yfinance-based news data fetching functions."""

import contextlib
from datetime import UTC, datetime

import yfinance as yf
from dateutil.relativedelta import relativedelta

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.date_window import coverage_gap, in_window
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.dataflows.vendors.yahoo import news_capture, provider_fixtures
from tradingagents.dataflows.vendors.yahoo.common import yf_retry


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format (handles nested 'content' structure).

    Yahoo sends some fields as null rather than leaving them out, so each falls
    back to its default on a null as well as on a missing key (#1458).
    """
    content = article.get("content")
    if isinstance(content, dict):
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        pub_date_str = content.get("pubDate") or ""
        pub_date = None
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))

        return {
            "title": content.get("title") or "No title",
            "summary": content.get("summary") or "",
            "publisher": (content.get("provider") or {}).get("displayName") or "Unknown",
            "link": url_obj.get("url") or "",
            "pub_date": pub_date,
        }
    # Fallback for flat structure. Parse the epoch publish time so flat
    # articles are date-filterable too (otherwise they bypass the
    # historical window and leak future news, #992/#1007).
    pub_date = None
    ts = article.get("providerPublishTime")
    if ts:
        # Epoch seconds are UTC; parse them as UTC-aware so filtering does
        # not shift with the host timezone (#1126).
        with contextlib.suppress(ValueError, OSError, TypeError):
            pub_date = datetime.fromtimestamp(ts, tz=UTC)
    return {
        "title": article.get("title") or "No title",
        "summary": article.get("summary") or "",
        "publisher": article.get("publisher") or "Unknown",
        "link": article.get("link") or "",
        "pub_date": pub_date,
    }


def _search_news(canonical: str, limit: int) -> tuple[list, bool]:
    """Yahoo search's articles tagged with ``canonical``, and whether it knows the symbol.

    Search answers when the quote feed is empty, but its articles are a
    relevance-picked sample, and some are tagged loosely; only those tagged with
    the symbol are about it.
    """
    search = provider_fixtures.search_news(
        canonical, canonical, limit,
        lambda: yf_retry(lambda: yf.Search(canonical, news_count=limit)),
    )
    if search is None:  # Yahoo answered "not found": its search is down
        return [], False
    tagged = [
        a for a in (search.news or [])
        if canonical in (t.upper() for t in a.get("relatedTickers") or [])
    ]
    knows = any((q.get("symbol") or "").upper() == canonical for q in search.quotes or [])
    return tagged, knows or bool(search.news)


def _format_articles(articles: list[dict]) -> str:
    out = ""
    for data in articles:
        out += f"### {data['title']} (source: {data['publisher']})\n"
        if data["summary"]:
            out += f"{data['summary']}\n"
        if data["link"]:
            out += f"Link: {data['link']}\n"
        out += "\n"
    return out


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """News about ``ticker`` published in the window, from Yahoo Finance.

    The symbol's quote feed comes first. When it is empty, Yahoo search serves
    the articles tagged with the symbol; when it has none, or neither answers,
    Yahoo news is unavailable, which is not an absence of news, and a configured
    next vendor is tried. Search results are a sample, so finding none in the
    window never reads as "no news".
    """
    article_limit = get_config()["news_article_limit"]
    # Separate the fetch pool from the delivered limit (same principle as global
    # news): Yahoo's ticker feed only returns the newest N articles, so fetching
    # exactly the deliver limit (8) can miss the as_of window entirely (all newest
    # items dated after ``as_of``). Fetch a bounded, deeper candidate pool, then
    # date-filter/dedupe and deliver at most ``article_limit`` to the LLM.
    TICKER_NEWS_FETCH_FLOOR = 50
    fetch_limit = max(article_limit, TICKER_NEWS_FETCH_FLOOR)
    # Query Yahoo with the canonical symbol, like every other yfinance path —
    # a raw broker/forex/crypto alias (XAUUSD, BTCUSD) otherwise silently
    # returns no news. Keep the user's ticker in the report header.
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"
    subject = f"news for {ticker}{resolved}"
    feed = provider_fixtures.news_list(
        canonical, lambda: yf_retry(lambda: yf.Ticker(canonical).get_news(count=fetch_limit)),
        count=fetch_limit,
    ) or []
    articles = [_extract_article_data(a) for a in feed]
    used_search_fallback = False
    if not feed:
        found, answered = _search_news(canonical, fetch_limit)
        if not answered:
            raise VendorUnavailableError(f"Yahoo Finance returned no news response for {canonical}")
        if not found:
            # With the quote feed empty, no tagged article says nothing about the
            # company's news (Yahoo tags no article with most non-US listings).
            raise VendorUnavailableError(f"Yahoo Finance has no news articles tagged {canonical}")
        articles = [_extract_article_data(a) for a in found]
        used_search_fallback = True

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    # Keep only articles within the requested window (look-ahead safe); de-dupe by
    # title; deliver at most ``article_limit``.
    in_range = [a for a in articles if in_window(a["pub_date"], start_dt, end_dt)]
    # The quote feed answers newest-first and its pool is bounded, so a run dated
    # at the window's upper edge can fetch a deep-but-still-all-future pool with
    # zero in-window articles even though Yahoo *has* in-window news. Yahoo search
    # returns the articles tagged with the symbol, which reaches further back, so
    # when the feed yields nothing in the window, consult search as a supplement
    # before reporting a coverage gap. Search is best-effort observation: a
    # failure or an empty tagged set leaves the feed result to be reported as-is
    # (the coverage-gap notice), never a crash and never future news.
    if feed and not in_range:
        try:
            found, _answered = _search_news(canonical, fetch_limit)
        except Exception:
            found = []
        if found:
            used_search_fallback = True
            articles = articles + [_extract_article_data(a) for a in found]
            in_range = [a for a in articles if in_window(a["pub_date"], start_dt, end_dt)]
    seen = set()
    deduped = []
    for a in in_range:
        t = a.get("title")
        if t and t not in seen:
            seen.add(t)
            deduped.append(a)
    delivered_articles = deduped[:article_limit]
    cap = news_capture.active()
    if cap is not None:
        # Observation only: fetch vs delivered are distinct (fetch_limit>article_limit).
        delivered = _format_articles(delivered_articles).count("### ")
        cap.record_ticker_call({
            "ticker": ticker,
            "requested_limit": fetch_limit,
            "delivered_limit": article_limit,
            "feed_nonempty": bool(feed),
            "used_search_fallback": used_search_fallback,
            "fetched_count": len(articles),
            "windowed_count": len(in_range),
            "deduped_count": len(deduped),
            "formatted_count": delivered,
            "delivered_count": delivered,
        })
    if delivered_articles:
        return f"## {ticker}{resolved} News, from {start_date} to {end_date}:\n\n{_format_articles(delivered_articles)}"

    if not feed:
        return (f"<Yahoo Finance news unavailable for {start_date}..{end_date}: Yahoo search "
                f"returns only a sample of recent articles about {canonical}, so this is not "
                f"an absence of {subject}>")
    gap = coverage_gap(
        (a["pub_date"] for a in articles),
        start_date, end_date, "Yahoo Finance news", subject,
    )
    return gap or f"No news found for {ticker}{resolved} between {start_date} and {end_date}"


def get_global_news_yfinance(
    as_of_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    Retrieve global/macro economic news using yfinance Search.

    Args:
        as_of_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles to return. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string containing global news articles
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    # Distance between the fetch pool (how many candidates we ask Yahoo for) and
    # the delivered limit (how many we hand to the LLM). Yahoo's search only
    # serves the newest articles, so a small fetch size can miss the requested
    # as_of window entirely (newest N all fall after ``as_of``). Fetching a
    # bounded deeper pool lets the date filter/ de-dupe find in-window articles,
    # while delivery stays capped by the configured limit (LLM input unchanged).
    GLOBAL_NEWS_FETCH_FLOOR = 50
    # ``global_news_article_limit`` is the configured MAXIMUM per call. An
    # explicit ``limit`` may lower it but must never exceed it: without this
    # clamp a model that passes limit=30/50 bypasses the configured cap entirely.
    config_cap = config["global_news_article_limit"]
    delivered_limit = config_cap if limit is None else min(limit, config_cap)
    # Bounded candidate pool per query; never paginates (one Search per query).
    fetch_limit = max(delivered_limit, GLOBAL_NEWS_FETCH_FLOOR)
    search_queries = config["global_news_queries"]

    curr_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    in_window_news = []
    seen_titles = set()
    observer = news_capture.active()

    for query in search_queries:
        found = provider_fixtures.search_news_list(
            query, "", fetch_limit,
            lambda q=query: yf_retry(lambda: yf.Search(
                query=q,
                news_count=fetch_limit,
                enable_fuzzy_query=True,
            ).news),
        )

        fetched = len(found or [])
        windowed = 0
        added = 0
        for article in found or []:
            # Window first: out-of-window articles are dropped before de-dupe so
            # they neither spend the delivered budget nor leak future news.
            data = _extract_article_data(article)
            if not in_window(data["pub_date"], start_dt, curr_dt):
                continue
            windowed += 1
            if data["title"] and data["title"] not in seen_titles:
                seen_titles.add(data["title"])
                in_window_news.append(data)
                added += 1

        if observer is not None:
            # Observation only: counts from this real query; fetch vs deliver distinct.
            observer.record_global_query({
                "query": query,
                "requested_limit": fetch_limit,       # actual provider fetch size
                "delivered_limit": delivered_limit,   # cap on what the LLM may read
                "fetched_count": fetched,
                "windowed_count": windowed,
                "deduped_added": added,
            })

        # Early stop only once we have enough in-window, de-duplicated articles to
        # fill the delivered budget; otherwise keep searching the remaining queries.
        if len(in_window_news) >= delivered_limit:
            break

    news_str = _format_articles(in_window_news[:delivered_limit])

    if observer is not None:
        delivered = news_str.count("### ")
        observer.record_global_query({
            "query": None,
            "summary": True,
            "delivered_limit": delivered_limit,
            "formatted_count": delivered,
            "delivered_count": delivered,
            "total_in_window": len(in_window_news),
        })

    # Nothing fell inside the window -> say so rather than return an
    # empty-bodied report (#993).
    if not news_str:
        # Results merge several fuzzy searches, so their timestamps prove no
        # continuous coverage; judge the window against the present only.
        gap = coverage_gap((), start_date, as_of_date, "Yahoo Finance global news", "market news")
        return gap or f"No global news found between {start_date} and {as_of_date}"

    return f"## Global Market News, from {start_date} to {as_of_date}:\n\n{news_str}"
