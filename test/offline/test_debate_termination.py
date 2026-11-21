"""FR-02: the debate terminates at its cap and records why.

The research debate runs bull and bear once each per round, so it ends when
``count >= 2 * max_debate_rounds`` and the Research Manager adjudicates. With
``max_debate_rounds = 0`` there is no round to run: the very first check must
route straight to the Research Manager rather than to a researcher. The risk
debate follows the same shape with three speakers per round.

The recorded termination reason lives in the debate state, which is what the
requirement's fit criterion reads (``convergence_rounds`` and
``termination_reason``). That field is asserted separately and is allowed to
fail until the source records it; see the module note on the third test.
"""

import pytest

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


@pytest.mark.unit
def test_termination_reason_is_recorded():
    """FR-02 also requires the reason to be recorded alongside the round count.

    TEST-FIRST (expected red): ``termination_reason`` is not yet a field of
    ``InvestDebateState``, so reading it below raises ``KeyError`` today. This
    assertion encodes FR-02 and will stay red until C adds the field to the
    debate state. The router decision ("Research Manager") is already correct;
    only the recorded provenance is missing. Do not weaken this to make it pass.
    """
    logic = ConditionalLogic(max_debate_rounds=0)
    state = _debate_state(count=0)
    assert logic.should_continue_debate(state) == "Research Manager"
    debate = state["investment_debate_state"]
    assert debate["termination_reason"] == "max_rounds"
