"""Round 2 fixtures for external tools (macro FRED, prediction Polymarket, news count).

Offline; no network, no LLM. Verifies record/replay of the ANALYST-VISIBLE text for
macro + prediction, the news fixture key including article_limit, strict replay
(no live call), missing/SHA errors, manifest, and fixtures-off no-op.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

import tradingagents.agents.tools as tools
import tradingagents.dataflows.vendors.yahoo.news as news
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.vendors.yahoo import provider_fixtures as pf

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- macro (FRED)
def test_macro_record_then_replay_no_network(tmp_path):
    sentinel = "DATA_UNAVAILABLE: optional macro_data could not be retrieved (FRED_API_KEY ...)"
    with mock.patch.object(tools, "route_to_vendor", return_value=sentinel) as rv:
        with pf.recording(tmp_path):
            out = tools.get_macro_indicators.func("cpi", "2026-11-18", 365, trade_date="2026-11-18")
    assert out == sentinel
    rv.assert_called_once()
    # Replay: route_to_vendor must NOT be called (network forbidden).
    boom = mock.MagicMock(side_effect=AssertionError("no network on replay"))
    with mock.patch.object(tools, "route_to_vendor", boom):
        with pf.replaying(tmp_path):
            rep = tools.get_macro_indicators.func("cpi", "2026-11-18", 365, trade_date="2026-11-18")
    assert rep == sentinel
    boom.assert_not_called()


def test_macro_key_includes_params(tmp_path):
    with mock.patch.object(tools, "route_to_vendor", return_value="FRED out"):
        with pf.recording(tmp_path):
            tools.get_macro_indicators.func("cpi", "2026-11-18", 365, trade_date="2026-11-18")
            tools.get_macro_indicators.func("unemployment", "2026-11-18", 90, trade_date="2026-11-18")
    keys = [e["key"] for e in pf.FixtureStore(tmp_path, "record").manifest() if e["kind"] == "macro"]
    assert any("cpi" in k and "365" in k for k in keys)
    assert any("unemployment" in k and "90" in k for k in keys)


# ------------------------------------------------------- prediction (Polymarket)
def test_prediction_record_then_replay_no_network(tmp_path):
    text = "## Prediction Markets: Fed rate cut\n- 0.62 ..."
    with mock.patch.object(tools, "route_to_vendor", return_value=text):
        with pf.recording(tmp_path):
            out = tools.get_prediction_markets.func("Fed rate cut", 6, trade_date="2026-11-18")
    assert out == text
    boom = mock.MagicMock(side_effect=AssertionError("no network on replay"))
    with mock.patch.object(tools, "route_to_vendor", boom):
        with pf.replaying(tmp_path):
            rep = tools.get_prediction_markets.func("Fed rate cut", 6, trade_date="2026-11-18")
    assert rep == text
    boom.assert_not_called()


def test_prediction_missing_fixture_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="fixture missing"):
        with pf.replaying(tmp_path):
            tools.get_prediction_markets.func("Fed rate cut", 6, trade_date="2026-11-18")


def test_prediction_sha_mismatch_raises(tmp_path):
    with mock.patch.object(tools, "route_to_vendor", return_value="pred-text"):
        with pf.recording(tmp_path):
            tools.get_prediction_markets.func("x", 3, trade_date="2026-11-18")
    # Corrupt the stored object body -> its .ref sha256 no longer matches.
    obj = next((tmp_path / "objects").glob("*.json"))
    obj.write_text("{corrupted")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        with pf.replaying(tmp_path):
            tools.get_prediction_markets.func("x", 3, trade_date="2026-11-18")


# --------------------------------------------------------- Ticker news count key
class _T:
    def __init__(self, symbol): self.symbol = symbol
    def get_news(self, count=None):
        return [{"content": {"title": f"{self.symbol}-{i}", "summary": "s",
                "provider": {"displayName": "X"}, "canonicalUrl": {"url": "u"},
                "pubDate": "2026-11-17T00:00:00Z"}} for i in range(min(count or 0, 6))]


def test_news_key_includes_article_limit(tmp_path):
    set_config({"news_article_limit": 8})
    with mock.patch.object(news.yf, "Ticker", _T):
        with pf.recording(tmp_path):
            news.get_news_yfinance("NVDA", "2026-11-12", "2026-11-18")
    keys = [e["key"] for e in pf.FixtureStore(tmp_path, "record").manifest() if e["kind"] == "news"]
    # key now reflects the fetch pool (>=50), which is >= the deliver limit 8
    assert any(k.startswith("NVDA") for k in keys), keys


def test_news_different_limit_is_different_fixture(tmp_path):
    with mock.patch.object(news.yf, "Ticker", _T):
        with pf.recording(tmp_path):
            set_config({"news_article_limit": 8}); news.get_news_yfinance("NVDA", "2026-11-12", "2026-11-18")
            set_config({"news_article_limit": 3}); news.get_news_yfinance("NVDA", "2026-11-12", "2026-11-18")
    keys = sorted(e["key"] for e in pf.FixtureStore(tmp_path, "record").manifest() if e["kind"] == "news")
    # Both configs (8 and 3) fetch the same floored pool (50) -> same fixture key.
    assert len(keys) == 1 and keys[0].startswith("NVDA"), keys


# --------------------------------------------------------------- off-mode noop
def test_off_mode_is_passthrough_no_files(tmp_path):
    with mock.patch.object(tools, "route_to_vendor", return_value="live-text") as rv:
        assert tools.get_prediction_markets.func("x", 2, trade_date="2026-11-18") == "live-text"
    rv.assert_called_once()
    assert pf.active() is None
    assert list(tmp_path.rglob("*")) == []


def test_manifest_lists_macro_and_prediction(tmp_path):
    with mock.patch.object(tools, "route_to_vendor", return_value="t"):
        with pf.recording(tmp_path):
            tools.get_macro_indicators.func("cpi", "2026-11-18", 365, trade_date="2026-11-18")
            tools.get_prediction_markets.func("x", 2, trade_date="2026-11-18")
    kinds = {e["kind"] for e in pf.FixtureStore(tmp_path, "record").manifest()}
    assert {"macro", "prediction"} <= kinds
