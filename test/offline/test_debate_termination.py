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
from tradingagents.agents.researchers.debate_schemas import DebateStance, IdeaCard, ResearcherTurn
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


def _researcher_state(count=0, *, bull_idea_cards=None, pending_bull_cards=None,
                      debate_rounds=None, termination_reason="", convergence_rounds=None):
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
            "bull_idea_cards": bull_idea_cards or [],
            "bear_idea_cards": [],
            "debate_rounds": debate_rounds or [],
            "convergence_rounds": convergence_rounds,
            "termination_reason": termination_reason,
            "converged": False,
            "pending_bull_cards": pending_bull_cards or [],
            "last_turn_status": {},
            "debate_record": {},
        },
    }


def _bear_llm(argument="bear prose", cards=None):
    """A MagicMock LLM whose structured binding returns a bare ResearcherTurn."""
    structured = mock.MagicMock()
    structured.invoke.return_value = ResearcherTurn(argument=argument, cards=cards or [])
    llm = mock.MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _card(card_id, claim, stance=DebateStance.BEARISH):
    return IdeaCard(
        id=card_id, claim=claim, evidence="evidence", stance=stance,
        uncertainty="what would falsify this", osborn_rule="defer_judgement", builds_on=[],
    )


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


# --------------------------------------------------------------------------- #
# FR-02: the converged path.
#
# Convergence is structural and round-to-round (see debate._round_converged): a
# round converges when BOTH sides introduce no claim they did not already carry
# in the *previous* round. Two consequences shape these tests:
#
#   * Round 1 can never converge -- `converged = bool(prev_rounds) and ...`, so
#     there must be a completed prior round to compare against. The earliest a
#     debate can converge is the second round the bear closes, which records
#     `convergence_rounds == 2`. Asserting 1 would be asserting a value the
#     source can never produce.
#   * Both bull and bear must be identical across the two rounds: _round_converged
#     returns False if *either* side is empty, so a test that varied only the bear
#     cards while the bull side was empty would never converge for the wrong reason.
#
# The bear closes each round. Round 1 is driven first to populate debate_rounds;
# its returned state is then fed into round 2, exactly as the graph would.
# --------------------------------------------------------------------------- #


def _close_round_one(bull_cards, bear_cards):
    """Close round 1: the first bear turn, which records the round-1 trace."""
    with mock.patch.object(debate, "max_debate_rounds", lambda: 3):
        out = create_bear_researcher(_bear_llm(cards=bear_cards))(
            _researcher_state(count=1, pending_bull_cards=bull_cards))
    return out["investment_debate_state"]


def _close_round_two(round_one, bull_cards, bear_cards):
    """Close round 2 from round 1's recorded state."""
    with mock.patch.object(debate, "max_debate_rounds", lambda: 3):
        out = create_bear_researcher(_bear_llm(cards=bear_cards))(
            _researcher_state(
                count=3,
                bull_idea_cards=bull_cards,
                pending_bull_cards=bull_cards,
                debate_rounds=round_one["debate_rounds"],
                termination_reason=round_one["termination_reason"],
                convergence_rounds=round_one["convergence_rounds"],
            ))
    return out["investment_debate_state"]


@pytest.mark.unit
def test_debate_converges_when_both_sides_repeat_their_cards():
    """Identical bull and bear cards in round 2 add nothing over round 1, so the
    debate converges at round 2 and records ``converged`` as the reason."""
    bull = [_card("bull-x", "AI backlog", DebateStance.BULLISH)]
    bear = [_card("bear-x", "margin compression", DebateStance.BEARISH)]

    round_one = _close_round_one(bull, bear)
    assert round_one["converged"] is False  # round 1 cannot converge

    round_two = _close_round_two(round_one, bull, bear)
    assert round_two["termination_reason"] == debate.CONVERGED
    assert round_two["converged"] is True
    assert round_two["convergence_rounds"] == 2


@pytest.mark.unit
def test_debate_does_not_converge_when_a_side_adds_a_new_card():
    """A new bear claim in round 2 is progress, so the debate does not converge."""
    bull = [_card("bull-x", "AI backlog", DebateStance.BULLISH)]
    bear_round_one = [_card("bear-x", "margin compression", DebateStance.BEARISH)]
    bear_round_two = [_card("bear-y", "valuation risk", DebateStance.BEARISH)]

    round_one = _close_round_one(bull, bear_round_one)
    round_two = _close_round_two(round_one, bull, bear_round_two)

    assert round_two["converged"] is False
    assert round_two["termination_reason"] != debate.CONVERGED
    assert round_two["convergence_rounds"] is None
