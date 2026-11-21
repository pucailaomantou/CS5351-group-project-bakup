"""Round 2 market-history replay index reconstruction tests (offline).

A recorded yfinance history CSV carries mixed UTC offsets across a DST change
(e.g. -05:00 winter / -04:00 summer). Naive read gives a plain Index with no
.tz, breaking downstream `df.index.tz`. These tests verify the replay rebuilds a
tz-aware DatetimeIndex that preserves the LOCAL wall-clock dates and row order
(DST-aware), and that `get_YFin_data_online` runs on it, all with NO network.
"""

from __future__ import annotations

from unittest import mock

import pandas as pd
import pytest

import tradingagents.dataflows.vendors.yahoo.market as market
from tradingagents.dataflows.vendors.yahoo import provider_fixtures as pf

pytestmark = pytest.mark.unit


def _mixed_tz_frame():
    # Winter (EST -05:00) .. summer (EDT -04:00) .. winter again, single exchange
    # tz America/New_York: local wall-clock dates are midnight on each day.
    dates = ["2021-11-19", "2022-03-11", "2022-03-14", "2022-06-15", "2022-11-15"]
    idx = pd.DatetimeIndex(pd.to_datetime(dates).tz_localize("America/New_York"), name="Date")
    return pd.DataFrame(
        {"Open": [1.0 + i for i in range(len(dates))],
         "High": [2.0 + i for i in range(len(dates))],
         "Low": [0.5 + i for i in range(len(dates))],
         "Close": [1.5 + i for i in range(len(dates))],
         "Volume": [100 + i for i in range(len(dates))]},
        index=idx,
    )


def test_recorded_csv_has_mixed_offsets(tmp_path):
    df = _mixed_tz_frame()
    with pf.recording(tmp_path) as s:
        s.save_csv("market", "NVDA|a|b", lambda fh: df.to_csv(fh))
    obj = next((tmp_path / "objects").glob("*.csv"))
    text = obj.read_text()
    assert "-05:00" in text and "-04:00" in text  # DST boundary present


def test_replay_rebuilds_tz_aware_index_and_local_dates(tmp_path):
    df = _mixed_tz_frame()
    with pf.recording(tmp_path) as s:
        s.save_csv("market", "NVDA|a|b", lambda fh: df.to_csv(fh))
    with pf.replaying(tmp_path):
        out = pf.history("NVDA_a_b", lambda: (_ for _ in ()).throw(AssertionError("no live")))
    # DatetimeIndex with a real tz
    assert isinstance(out.index, pd.DatetimeIndex)
    assert out.index.tz is not None
    # Local wall-clock dates preserved exactly, in the original order.
    assert [d.strftime("%Y-%m-%d") for d in out.index] == \
           [d.strftime("%Y-%m-%d") for d in df.index]
    assert out.index.is_monotonic_increasing
    # And after the downstream tz_localize(None) the local dates still match.
    dropped = out.index.tz_localize(None)
    assert [d.strftime("%Y-%m-%d") for d in dropped] == \
           [d.strftime("%Y-%m-%d") for d in df.index]
    # Values preserved in order.
    assert list(out["Close"]) == list(df["Close"])


def test_dst_boundary_offset_changes_but_local_date_stable(tmp_path):
    df = _mixed_tz_frame()
    with pf.recording(tmp_path) as s:
        s.save_csv("market", "NVDA|a|b", lambda fh: df.to_csv(fh))
    with pf.replaying(tmp_path):
        out = pf.history("NVDA_a_b", lambda: (_ for _ in ()).throw(AssertionError("no live")))
    # 2022-03-11 (EST -05) vs 2022-03-14 (EDT -04): offset differs, local midnight kept.
    assert out.index[1].utcoffset() != out.index[2].utcoffset()
    assert out.index[1].hour == 0 and out.index[2].hour == 0


def test_get_yfin_data_online_replays_without_network(tmp_path):
    df = _mixed_tz_frame()
    # Record under a key that a fresh recording of get_YFin_data_online would produce.
    with pf.recording(tmp_path) as s:
        s.save_csv("market", "NVDA_2021-11-19_2022-11-16", lambda fh: df.to_csv(fh))
    boom = mock.MagicMock(side_effect=AssertionError("no live Yahoo"))
    with mock.patch.object(market.yf, "Ticker", boom):
        with pf.replaying(tmp_path):
            # Request the exact recorded window (end inclusive+1 day -> key match).
            out = market.get_YFin_data_online("NVDA", "2021-11-19", "2022-11-15")
    boom.assert_not_called()
    assert "Stock data for NVDA" in out
