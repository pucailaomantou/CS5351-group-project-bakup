"""FR-02: the debate terminates at its cap and records why.

The research debate runs bull and bear once each per round, so the router
(``ConditionalLogic.should_continue_debate``) ends it when
``count >= 2 * max_debate_rounds`` and the Research Manager adjudicates. With
``max_debate_rounds = 0`` there is no round to run: the very first check routes
straight to the Research Manager rather than to a researcher. The risk debate
follows the same shape with three speakers per round.

The router decides *where* to go; it does not write the state. The
``termination_reason`` and ``convergence_rounds`` fields are written by the
researcher nodes (the bear speaks second and closes each round) and the Research
Manager. So proving FR-02's "records why it stopped" requires driving the
*writer*, not the router: the last test here invokes the real bear node with the
round cap at zero and reads the recorded fields back out of the state it returns.
"""

from unittest import mock

import pytest

from tradingagents.agents.researchers import debate
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.debate_schemas import ResearcherTurn
from tradingagents.graph.conditional_logic import ConditionalLogic


def _debate_state(current_response="Bull Researcher", count=0):
    return {"investment_debate_state": {"current_response": current_response, "count": count}}


def _risk_state(latest_speaker="Aggressive Analyst", count=0):
    return {"risk_debate_state": {"latest_speaker": latest_speaker, "count": count}}


@pytest.mark.unit
def test_zero_debate_rounds_terminates_immediately():
    """max_debate_rounds = 0: `count >= 0` holds at once, so no round runs."""
    logic = ConditionalLogic(max_debate_rounds=0)
    assert logic.should_continue_debate(_debate_state(count=0)) == "Research Manager"


@pytest.mark.unit
def test_debate_terminates_at_the_round_cap():
    """One round is two turns; once both are taken the manager adjudicates."""
    logic = ConditionalLogic(max_debate_rounds=1)
    assert logic.should_continue_debate(_debate_state(count=2)) == "Research Manager"


@pytest.mark.unit
@pytest.mark.parametrize("current_response, expected", [
    ("Bull Researcher", "Bear Researcher"),
    ("Bear Researcher", "Bull Researcher"),
])
def test_debate_alternates_between_sides_before_the_cap(current_response, expected):
    logic = ConditionalLogic(max_debate_rounds=1)
    assert logic.should_continue_debate(_debate_state(current_response, count=1)) == expected


@pytest.mark.unit
def test_zero_risk_rounds_terminates_immediately():
    """max_risk_discuss_rounds = 0: `count >= 0` holds at once."""
    logic = ConditionalLogic(max_risk_discuss_rounds=0)
    assert logic.should_continue_risk_analysis(_risk_state(count=0)) == "Portfolio Manager"


# --------------------------------------------------------------------------- #
# FR-02: the writer records termination_reason and convergence_rounds.
#
# These drive the real bear node (create_bear_researcher) — the node that closes
# each round and writes the provenance fields — rather than the router, which
# only routes. The bear node reads the cap from debate.max_debate_rounds(), so we
# patch that to the case under test. The structured model is a MagicMock whose
# bound output returns a ResearcherTurn, exactly as the other offline node tests
# drive it; no provider and no network are involved.
# --------------------------------------------------------------------------- #


def _researcher_state(count=0):
    """Minimal AgentState for the bear researcher node."""
    return {
        "company_of_interest": "NVDA",
        "asset_type": "stock",
        "market_report": "market R",
        "sentiment_report": "",
        "news_report": "news R",
        "fundamentals_report": "",
        "instrument_context": "NVDA",
        "messages": [],
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "count": count,
            "bull_idea_cards": [],
            "bear_idea_cards": [],
            "debate_rounds": [],
            "convergence_rounds": None,
            "termination_reason": "",
            "converged": False,
            "pending_bull_cards": [],
            "last_turn_status": {},
            "debate_record": {},
        },
    }


def _bear_llm(argument="bear prose"):
    """A MagicMock LLM whose structured binding returns a bare ResearcherTurn."""
    structured = mock.MagicMock()
    structured.invoke.return_value = ResearcherTurn(argument=argument, cards=[])
    llm = mock.MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
def test_bear_node_records_max_rounds_termination():
    """max_debate_rounds = 0: the bear closes round 1, which is already past the
    cap, so it records ``max_rounds`` and leaves ``convergence_rounds`` None."""
    bear = create_bear_researcher(_bear_llm())
    with mock.patch.object(debate, "max_debate_rounds", lambda: 0):
        out = bear(_researcher_state(count=0))
    debate_state = out["investment_debate_state"]
    assert debate_state["termination_reason"] == debate.MAX_ROUNDS
    assert debate_state["convergence_rounds"] is None
    assert debate_state["count"] == 1


@pytest.mark.unit
def test_bear_node_records_max_rounds_at_a_one_round_cap():
    """A one-round cap that is not converged closes on ``max_rounds`` (round 1
    is the cap), proving the field is written by the real node for the ordinary
    capped case too, not only the degenerate zero."""
    bear = create_bear_researcher(_bear_llm())
    with mock.patch.object(debate, "max_debate_rounds", lambda: 1):
        out = bear(_researcher_state(count=0))
    debate_state = out["investment_debate_state"]
    assert debate_state["termination_reason"] == debate.MAX_ROUNDS
    assert debate_state["convergence_rounds"] is None
    assert debate_state["converged"] is False
