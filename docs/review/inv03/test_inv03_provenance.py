"""INV-03 provenance — pytest candidate for E review.

Status: review candidate, not yet part of the official suite.
Target on acceptance: test/offline/test_inv03_provenance.py (E owns test/offline).
Offline only: no network, no real LLM/data API.

Covers: real old snapshot date (not request date), impossible/missing date,
unavailable responses (error / DATA_UNAVAILABLE / NO_DATA_AVAILABLE),
fundamentals period_end vs filing bound, multi-period retention, duplicate calls,
conflict handling, reducer algebra (idempotent/commutative/associative/no-mutation),
validation, N versions, cross-run isolation, real parent StateGraph propagation,
and actual analyst node execution via stubs.
"""
from __future__ import annotations

import copy

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from tradingagents.agents.analysts.fundamentals_analyst import (
    _fundamentals_input_provenance,
)
from tradingagents.agents.analysts.market_analyst import (
    _snapshot_input_provenance,
)
from tradingagents.agents.state import AgentState, _merge_input_provenance as M
from tradingagents.graph.analyst_execution import AnalystNodeSpec
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import _analyst_graph

pytestmark = pytest.mark.unit

SNAP_OLD = (
    "## Verified market data snapshot for NVDA\n\n"
    "- Requested analysis date: 2026-11-25\n"
    "- Latest trading row used: 2026-11-18\n"
)
EDGAR_MULTI = (
    "# Balance Sheet for NVDA (quarterly), USD in millions\n"
    "# SEC EDGAR facts filed on or before 2026-11-25, at the values filed then\n\n"
    "Period,Assets\n2026-09-30Q3,100\n2026-06-30Q2,90\n"
)


def _snap(content, cid="c1", name="get_verified_market_snapshot", status="success"):
    return ToolMessage(content=content, tool_call_id=cid, name=name, status=status)


def _entry(**kw):
    base = {"analyst": "market", "tool": "t", "call_id": "c1", "input_class": "market_close",
            "period_id": "", "as_of": "2026-11-18", "precision": "date",
            "semantics": "latest_trading_row", "evidence": "e", "available": True,
            "time_reliable": True, "missing_reason": ""}
    base.update(kw)
    return base


# --- snapshot: real date vs request / invalid / unavailable -----------------

def test_snapshot_uses_real_latest_row_date_not_request_date():
    p = _snapshot_input_provenance([_snap(SNAP_OLD)])
    assert len(p) == 1
    assert p[0]["as_of"] == "2026-11-18" and p[0]["semantics"] == "latest_trading_row"
    assert p[0]["time_reliable"] is True and p[0]["available"] is True


def test_snapshot_impossible_calendar_date_is_unreliable_not_backfilled():
    p = _snapshot_input_provenance([_snap("- Latest trading row used: 2026-02-30\n")])
    assert p[0]["as_of"] is None and p[0]["precision"] == "unknown"
    assert p[0]["time_reliable"] is False and p[0]["missing_reason"] == "no_reliable_date"


@pytest.mark.parametrize("content,status,reason", [
    ("boom", "error", "tool_error"),
    ("DATA_UNAVAILABLE: none", "success", "vendor_unavailable"),
    ("NO_DATA_AVAILABLE: none", "success", "no_data_available"),
])
def test_snapshot_unavailable_is_not_recorded_as_usable(content, status, reason):
    p = _snapshot_input_provenance([_snap(content, status=status)])
    assert p[0]["available"] is False and p[0]["missing_reason"] == reason
    assert p[0]["time_reliable"] is False and p[0]["as_of"] is None


def test_snapshot_duplicate_call_id_scanned_once():
    p = _snapshot_input_provenance([_snap(SNAP_OLD, "cX"), _snap(SNAP_OLD, "cX")])
    assert len(p) == 1


def test_non_snapshot_tool_ignored():
    assert _snapshot_input_provenance([_snap(SNAP_OLD, name="get_stock_data")]) == []


# --- fundamentals: period vs filing bound, multi-period --------------------

def test_edgar_multi_period_keeps_each_period_and_never_filing_bound():
    p = _fundamentals_input_provenance([_snap(EDGAR_MULTI, "e1", name="get_balance_sheet")])
    assert len(p) == 2
    assert {x["as_of"] for x in p} == {"2026-09-30", "2026-06-30"}
    assert all(x["semantics"] == "period_end" for x in p)
    assert all(x["as_of"] != "2026-11-25" for x in p)  # not the "filed on or before" bound


def test_profile_has_no_vintage():
    p = _fundamentals_input_provenance([_snap("# Company Fundamentals for NVDA\n\nX: 1\n", "f", name="get_fundamentals")])
    assert p[0]["available"] is True and p[0]["as_of"] is None
    assert p[0]["missing_reason"] == "no_vintage" and p[0]["time_reliable"] is False


# --- reducer algebra: idempotent / commutative / associative / no mutation -

def test_reducer_idempotent_commutative_associative():
    a = _entry(as_of="2026-11-18")
    b = _entry(as_of="2026-11-17", call_id="c2")
    c = _entry(input_class="fundamentals", call_id="c3", semantics="period_end", period_id="2026-09-30")
    assert M([a], [a]) == M([a], []) == [a]
    assert M([a], [b]) == M([b], [a])
    assert M(M([a], [b]), [c]) == M([a], M([b], [c]))


def test_reducer_does_not_mutate_inputs():
    a, b = [_entry()], [_entry(call_id="c2", as_of="2026-11-17")]
    ac, bc = copy.deepcopy(a), copy.deepcopy(b)
    M(a, b)
    assert a == ac and b == bc


def test_conflict_versions_kept_and_unreliable():
    m = M(M([_entry(as_of="2026-11-18")], [_entry(as_of="2026-11-17")]), [_entry(as_of="2026-11-16")])
    assert len(m) == 3 and all(x["time_reliable"] is False for x in m)


def test_conflict_marker_forces_unreliable_even_when_inputs_reliable():
    marked = _entry(missing_reason="conflict_kept_all", time_reliable=True)
    out = M([marked], [_entry(time_reliable=True, missing_reason="")])
    assert len(out) == 1 and out[0]["time_reliable"] is False
    assert out[0]["missing_reason"] == "conflict_kept_all"


def test_input_class_difference_not_merged_away():
    assert len(M([_entry(input_class="market_close")], [_entry(input_class="fundamentals")])) == 2


@pytest.mark.parametrize("bad", [
    {k: v for k, v in _entry().items() if k != "input_class"},       # missing key
    _entry(available="yes"),                                          # wrong type
    _entry(precision="sometimes"),                                    # bad precision
    _entry(as_of=123),                                                # bad as_of type
])
def test_malformed_entry_raises(bad):
    with pytest.raises((ValueError, TypeError)):
        M([bad], [])


def test_none_and_string_asof_sort_is_safe():
    out = M([_entry(as_of=None, precision="unknown", call_id="cN")], [_entry(as_of="2026-11-18", call_id="cS")])
    assert len(out) == 2


# --- initialisation / isolation + real parent StateGraph -------------------

def test_create_initial_state_isolates_runs():
    s1 = Propagator().create_initial_state("NVDA", "2026-11-18")
    s2 = Propagator().create_initial_state("NVDA", "2026-11-18")
    assert s1["input_provenance"] == [] and s2["input_provenance"] == []
    s1["input_provenance"].append(_entry())
    assert s2["input_provenance"] == []


@tool
def get_verified_market_snapshot(symbol: str, curr_date: str) -> str:
    """stub snapshot tool"""
    return SNAP_OLD


def _market_agent(state):
    msgs = state["messages"]
    has = any(isinstance(m, ToolMessage) and getattr(m, "name", None) == "get_verified_market_snapshot" for m in msgs)
    if not has:
        return {"messages": [AIMessage(content="", tool_calls=[{"name": "get_verified_market_snapshot",
                 "args": {"symbol": "NVDA", "curr_date": "2026-11-25"}, "id": "m1"}])], "market_report": "", "input_provenance": []}
    return {"messages": [AIMessage(content="report")], "market_report": "report",
            "input_provenance": _snapshot_input_provenance(msgs)}


def test_real_parent_state_graph_retains_provenance():
    spec = AnalystNodeSpec(key="market", agent_node="Market Analyst", report_key="market_report",
                           tools=(get_verified_market_snapshot,))
    sub = _analyst_graph(spec, _market_agent, max_tool_rounds=4)
    parent = StateGraph(AgentState)
    parent.add_node("Market Analyst", sub)
    parent.add_edge(START, "Market Analyst")
    parent.add_edge("Market Analyst", END)
    final = parent.compile().invoke(Propagator().create_initial_state("NVDA", "2026-11-25"))
    prov = final["input_provenance"]
    assert len(prov) == 1 and prov[0]["as_of"] == "2026-11-18" and prov[0]["input_class"] == "market_close"
    assert final["market_report"] == "report"


# --- actual analyst node execution (scripted model) ------------------------

# --- real vendor formats (round 2) -----------------------------------------

@pytest.mark.parametrize("content", [
    "# Balance Sheet data for NVDA (quarterly)\n,2026-09-30,2026-06-30\nTotalAssets,1,2\n",   # empty header
    "# Balance Sheet data for NVDA (quarterly)\nDate,2026-09-30,2026-06-30\nTotalAssets,1,2\n",  # Date header
    "# Balance Sheet data\nUnnamed: 0,Date,TotalAssets\n0,2026-09-30,1\n1,2026-06-30,2\n",       # Date column
])
def test_yahoo_csv_shapes_all_keep_periods(content):
    p = _fundamentals_input_provenance([_snap(content, "y", name="get_balance_sheet")])
    assert len(p) == 2 and {x["as_of"] for x in p} == {"2026-09-30", "2026-06-30"}


def test_edgar_multi_span_same_end_date_kept_distinct():
    edgar = ("# Balance Sheet for NVDA (quarterly)\n# SEC EDGAR facts filed on or before 2026-11-25\n\n"
             "Period,Assets\n2026-09-30,1\n2026-09-30 (6 months),2\n2026-09-30 (9 months),3\n")
    p = _fundamentals_input_provenance([_snap(edgar, "e", name="get_balance_sheet")])
    assert len(p) == 3 and len({x["period_id"] for x in p}) == 3
    assert {x["as_of"] for x in p} == {"2026-09-30"} and all(x["as_of"] != "2026-11-25" for x in p)


@pytest.mark.parametrize("content,tool", [
    ("# Balance Sheet for NVDA\n# Point-in-time as of: 2026-11-18\n\nBalance Sheet data is withheld for this date. ...", "get_balance_sheet"),
    ("# Company Fundamentals for NVDA\n# Point-in-time as of: 2026-11-18\n\nProfile fundamentals are withheld for this date. ...", "get_fundamentals"),
])
def test_withheld_notice_is_unavailable_and_not_dated_from_request(content, tool):
    p = _fundamentals_input_provenance([_snap(content, "w", name=tool)])
    assert len(p) == 1 and p[0]["available"] is False
    assert p[0]["missing_reason"] == "withheld_point_in_time" and p[0]["as_of"] is None


def test_success_but_no_time_distinguishable_from_withheld():
    p = _fundamentals_input_provenance([_snap("# Company Fundamentals for NVDA\n\nX: 1\n", "n", name="get_fundamentals")])
    assert p[0]["available"] is True and p[0]["missing_reason"] == "no_vintage"


def test_alpha_vantage_json_per_period():
    av = ('{"symbol":"NVDA","annualReports":[{"fiscalDateEnding":"2025-12-31"}],'
          '"quarterlyReports":[{"fiscalDateEnding":"2026-09-30"},{"fiscalDateEnding":"2026-06-30"}]}')
    p = _fundamentals_input_provenance([_snap(av, "av", name="get_income_statement")])
    assert len(p) == 3 and {x["as_of"] for x in p} == {"2025-12-31", "2026-09-30", "2026-06-30"}


def test_two_invalid_periods_not_merged():
    p = _fundamentals_input_provenance([_snap("# Balance Sheet\n,2026-02-30,2026-02-31\nTotalAssets,1,2\n", "b", name="get_balance_sheet")])
    assert len(p) == 2 and len({x["period_id"] for x in p}) == 2
    assert all(x["as_of"] is None and x["time_reliable"] is False for x in p)


def test_yahoo_date_column_preferred_over_empty_index():
    # Empty index header at col 0, real 'Date' at col 1: must use the Date column.
    p = _fundamentals_input_provenance([_snap("# BS\nUnnamed: 0,Date,TotalAssets\n0,2026-09-30,1\n1,2026-06-30,2\n", "d", name="get_balance_sheet")])
    assert len(p) == 2 and {x["as_of"] for x in p} == {"2026-09-30", "2026-06-30"}


def test_yahoo_date_as_row_index_kept():
    p = _fundamentals_input_provenance([_snap("# BS\n,TotalAssets\n2026-09-30,1\n2026-06-30,2\n", "r", name="get_balance_sheet")])
    assert len(p) == 2 and {x["as_of"] for x in p} == {"2026-09-30", "2026-06-30"}


def test_yahoo_invalid_dates_in_date_column_retained():
    p = _fundamentals_input_provenance([_snap("# BS\nUnnamed: 0,Date,TotalAssets\n0,2026-02-30,1\n1,2026-02-31,2\n", "i", name="get_balance_sheet")])
    assert len(p) == 2 and len({x["period_id"] for x in p}) == 2
    assert all(x["as_of"] is None and x["time_reliable"] is False for x in p)


class _ScriptedChat(BaseChatModel):
    """Self-contained scripted chat model: call the snapshot tool once, then report."""

    @property
    def _llm_type(self) -> str:
        return "scripted-inv03"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if not isinstance(messages[-1], ToolMessage):
            msg = AIMessage(content="", tool_calls=[{"name": "get_verified_market_snapshot",
                             "args": {"symbol": "NVDA", "curr_date": "2026-11-25"}, "id": "s1"}])
        else:
            msg = AIMessage(content="final report")
        return ChatResult(generations=[ChatGeneration(message=msg)])


def test_market_analyst_node_records_snapshot_provenance_via_real_node():
    from tradingagents.agents.analysts import market_analyst as MA
    node = MA.create_market_analyst(_ScriptedChat())
    init = Propagator().create_initial_state("NVDA", "2026-11-25")
    init["messages"] = [
        AIMessage(content="", tool_calls=[{"name": "get_verified_market_snapshot",
                   "args": {"symbol": "NVDA", "curr_date": "2026-11-25"}, "id": "s1"}]),
        ToolMessage(content=SNAP_OLD, tool_call_id="s1", name="get_verified_market_snapshot", status="success"),
    ]
    out = node(init)
    prov = out["input_provenance"]
    assert prov and prov[0]["as_of"] == "2026-11-18" and prov[0]["input_class"] == "market_close"
    assert out["market_report"] == "final report"


@tool
def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = "") -> str:
    """stub bs"""
    return EDGAR_MULTI


def test_fundamentals_analyst_node_records_period_end_provenance():
    from tradingagents.agents.analysts import fundamentals_analyst as FA
    node = FA.create_fundamentals_analyst(_ScriptedChat())
    init = Propagator().create_initial_state("NVDA", "2026-11-25")
    init["messages"] = [
        AIMessage(content="", tool_calls=[{"name": "get_balance_sheet",
                   "args": {"ticker": "NVDA", "freq": "quarterly", "curr_date": "2026-11-25"}, "id": "b1"}]),
        ToolMessage(content=EDGAR_MULTI, tool_call_id="b1", name="get_balance_sheet", status="success"),
    ]
    out = node(init)
    prov = out["input_provenance"]
    assert {x["as_of"] for x in prov} == {"2026-09-30", "2026-06-30"}
    assert all(x["semantics"] == "period_end" and x["input_class"] == "fundamentals" for x in prov)
