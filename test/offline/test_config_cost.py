"""COST-01: the three cost levers are the frozen 8 / 8 / 3.

The requirement (docs/req/requirements.yaml, COST-01) fixes
``max_tool_rounds = 8``, ``news_article_limit = 8`` and exactly three
``global_news_queries`` entries. The baseline shipped 20 / 20 / 5; the change to
8 / 8 / 3 is the work, not a given, so this test fails against the baseline and
passes only once the cost change lands. Do not relax these numbers to make a
test pass (AGENTS.md, "Invariants you must not break").

Each assertion reports the actual value alongside the expected one, so a
failure shows exactly which lever C missed rather than a bare ``20 == 8``.
"""

import pytest

from tradingagents.default_config import build_default_config


def _actual():
    cfg = build_default_config()
    return cfg["max_tool_rounds"], cfg["news_article_limit"], len(cfg["global_news_queries"])


@pytest.mark.unit
def test_max_tool_rounds_is_eight():
    actual = build_default_config()["max_tool_rounds"]
    assert actual == 8, f"max_tool_rounds is {actual}, expected 8"


@pytest.mark.unit
def test_news_article_limit_is_eight():
    actual = build_default_config()["news_article_limit"]
    assert actual == 8, f"news_article_limit is {actual}, expected 8"


@pytest.mark.unit
def test_three_global_news_queries():
    queries = build_default_config()["global_news_queries"]
    assert len(queries) == 3, f"global_news_queries has {len(queries)} entries, expected 3: {queries}"


@pytest.mark.unit
def test_cost_levers_are_8_8_3_together():
    """One view of all three levers, for a single readable failure."""
    tool_rounds, article_limit, query_count = _actual()
    assert (tool_rounds, article_limit, query_count) == (8, 8, 3), (
        f"COST-01 levers are {tool_rounds}/{article_limit}/{query_count}, expected 8/8/3"
    )
