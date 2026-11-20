"""Round 2 P0 cost-control tests (offline; no provider, no network).

Covers:
  P0-1  card count capped at MAX_CARDS_PER_SIDE; required fields/evidence kept;
        over-long fields clipped but non-empty; Research Manager still reads cards.
  P0-2  single-round debate omits the redundant own-side prior block but keeps the
        opponent block; multi-round keeps both; empty blocks omitted.
  Fallback / structured path unaffected (one-call guarantee preserved).
"""

from __future__ import annotations

from unittest import mock

import pytest

from tradingagents.agents.researchers import debate
from tradingagents.agents.researchers.debate_schemas import (
    DebateStance,
    IdeaCard,
    ResearcherTurn,
    card_to_dict,
    render_idea_cards,
)

pytestmark = pytest.mark.unit


def _card(i: int, stance=DebateStance.BULLISH, claim_len=20, ev_len=20, unc_len=20) -> IdeaCard:
    return IdeaCard(
        id=f"raw-{i}",
        claim="C" * claim_len,
        evidence="E" * ev_len,
        stance=stance,
        uncertainty="U" * unc_len,
    )


# ---------------------------------------------------------------- P0-1

def test_card_count_capped_to_limit():
    cards = [_card(i) for i in range(12)]
    out = debate.normalise_cards(cards, "bull", 1, [], [])
    assert len(out) == debate.MAX_CARDS_PER_SIDE == 5


def test_fewer_than_limit_kept():
    cards = [_card(i) for i in range(3)]
    out = debate.normalise_cards(cards, "bull", 1, [], [])
    assert len(out) == 3


def test_required_fields_and_evidence_preserved():
    cards = [_card(1, claim_len=10, ev_len=10, unc_len=10)]
    out = debate.normalise_cards(cards, "bull", 1, [], [])
    assert len(out) == 1
    c = out[0]
    for field in ("id", "claim", "evidence", "stance", "uncertainty", "osborn_rule", "builds_on"):
        assert field in c
    # Required fields are present AND non-empty (FR-01).
    assert c["claim"] and c["evidence"] and c["uncertainty"]
    assert c["stance"] in ("Bullish", "Bearish", "Neutral")


def test_overlong_fields_clipped_but_nonempty():
    cards = [_card(1, claim_len=900, ev_len=1500, unc_len=900)]
    out = debate.normalise_cards(cards, "bull", 1, [], [])
    c = out[0]
    assert len(c["claim"]) <= debate.MAX_CLAIM_CHARS and c["claim"]
    assert len(c["evidence"]) <= debate.MAX_EVIDENCE_CHARS and c["evidence"]
    assert len(c["uncertainty"]) <= debate.MAX_UNCERTAINTY_CHARS and c["uncertainty"]


def test_builds_on_reference_is_not_lost_by_cap():
    # A later card citing an earlier kept card keeps the link.
    a = _card(1)
    b = _card(2)
    b.builds_on = ["raw-1"]
    out = debate.normalise_cards([a, b], "bear", 1, [], [])
    assert out[1]["builds_on"] == [out[0]["id"]]


def test_osborn_instructions_mention_cap_and_lengths():
    text = debate.build_osborn_instructions()
    assert str(debate.MAX_CARDS_PER_SIDE) in text
    assert "claim" in text.lower()


def test_manager_still_reads_cards_after_cap():
    # render_idea_cards (what the RM consumes) renders all capped cards with ids
    # the rationale can cite — nothing required is dropped by the cap.
    cards = debate.normalise_cards([_card(i) for i in range(9)], "bull", 1, [], [])
    rendered = render_idea_cards(cards)
    for c in cards:
        assert c["id"] in rendered
    assert rendered.count("**Claim**") == len(cards)


# ---------------------------------------------------------------- P0-2

_OWN = [{"id": "bull-1-1", "claim": "c", "evidence": "e", "stance": "Bullish",
         "uncertainty": "u", "osborn_rule": "defer_judgement", "builds_on": []}]
_OPP = [{"id": "bear-1-1", "claim": "c", "evidence": "e", "stance": "Bearish",
         "uncertainty": "u", "osborn_rule": "defer_judgement", "builds_on": []}]


def test_single_round_omits_own_prior_keeps_opponent():
    with mock.patch.object(debate, "max_debate_rounds", lambda: 1):
        block = debate.render_prior_cards_block(_OWN, _OPP, side_label_own="bull", side_label_opp="bear")
    assert "Your cards so far" not in block         # own-side block omitted (no consumer)
    assert "Opponent (bear) cards so far" in block  # same-round responder still gets it


def test_multi_round_keeps_both_blocks():
    with mock.patch.object(debate, "max_debate_rounds", lambda: 3):
        block = debate.render_prior_cards_block(_OWN, _OPP, side_label_own="bull", side_label_opp="bear")
    assert "Your cards so far" in block
    assert "Opponent (bear) cards so far" in block


def test_empty_priors_emit_nothing():
    with mock.patch.object(debate, "max_debate_rounds", lambda: 1):
        assert debate.render_prior_cards_block([], [], side_label_own="bull", side_label_opp="bear") == ""


def test_no_placeholder_text_leaks():
    with mock.patch.object(debate, "max_debate_rounds", lambda: 1):
        block = debate.render_prior_cards_block([], [], side_label_own="bull", side_label_opp="bear")
    assert "none yet this debate" not in block


# ------------------------------------------------- P0 structured/fallback intact

class _StructuredLLM:
    """Returns a ResearcherTurn (parsed) — the one-call success path."""

    def __init__(self, turn):
        self.turn = turn
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return self.turn


def test_generate_turn_structured_success_one_call_capped():
    llm = _StructuredLLM(ResearcherTurn(argument="a real argument",
                                        cards=[_card(i) for i in range(8)]))
    arg, cards, status = debate.generate_turn(llm, "p", "bull", 1, [], [])
    assert status == "ok" and arg == "a real argument"
    assert llm.calls == 1
    assert len(cards) <= debate.MAX_CARDS_PER_SIDE


def test_generate_turn_none_binding_signals_plain_path():
    arg, cards, status = debate.generate_turn(None, "p", "bull", 1, [], [])
    assert arg is None and cards == [] and status == "no_structured"


# ---------------------------------------------- P0 boundary: node-level behaviour

from unittest.mock import MagicMock  # noqa: E402

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher  # noqa: E402
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher  # noqa: E402


def _researcher_state(*, bull_cards=None, bear_cards=None, count=0):
    """Minimal AgentState for a researcher node."""
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
            "bull_idea_cards": bull_cards or [],
            "bear_idea_cards": bear_cards or [],
            "debate_rounds": [],
            "convergence_rounds": None,
            "termination_reason": "",
            "converged": False,
            "pending_bull_cards": [],
            "last_turn_status": {},
            "debate_record": {},
        },
    }


def _researcher_llm(turn):
    """A MagicMock LLM whose structured binding captures the prompt and returns ``turn``."""
    captured = {}
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (captured.__setitem__("prompt", prompt) or turn)
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm, captured


def test_bull_node_zero_cards_is_handled():
    # Bull returns an argument with NO cards: the node must still succeed,
    # store an empty card list, and the RM fallback text applies (not a crash).
    turn = ResearcherTurn(argument="bull prose", cards=[])
    llm, _ = _researcher_llm(turn)
    out = create_bull_researcher(llm)(_researcher_state())
    ids = out["investment_debate_state"]
    assert ids["bull_idea_cards"] == []
    assert ids["current_response"].startswith("Bull Analyst:")
    assert ids["count"] == 1


def test_bear_node_zero_cards_is_handled():
    turn = ResearcherTurn(argument="bear prose", cards=[])
    llm, _ = _researcher_llm(turn)
    out = create_bear_researcher(llm)(_researcher_state(
        bull_cards=[{"id": "bull-1-1", "claim": "c", "evidence": "e", "stance": "Bullish",
                     "uncertainty": "u", "osborn_rule": "defer_judgement", "builds_on": []}]))
    ids = out["investment_debate_state"]
    assert ids["bear_idea_cards"] == []
    assert ids["current_response"].startswith("Bear Analyst:")


def test_bull_node_caps_more_than_five_cards():
    # Node-level: even if the model returns 9 cards, the stored set is capped.
    turn = ResearcherTurn(argument="bull", cards=[_card(i) for i in range(9)])
    llm, _ = _researcher_llm(turn)
    out = create_bull_researcher(llm)(_researcher_state())
    assert len(out["investment_debate_state"]["bull_idea_cards"]) == debate.MAX_CARDS_PER_SIDE


def test_bear_node_receives_opponent_cards_in_prompt():
    # Node-level P0-2: the bear prompt must still contain the opponent (bull)
    # cards, because the same-round responder genuinely consumes them.
    bull = [{"id": "bull-1-1", "claim": "UNIQUE_BULL_CLAIM", "evidence": "e", "stance": "Bullish",
             "uncertainty": "u", "osborn_rule": "defer_judgement", "builds_on": []}]
    turn = ResearcherTurn(argument="bear", cards=[_card(1, stance=DebateStance.BEARISH)])
    llm, captured = _researcher_llm(turn)
    create_bear_researcher(llm)(_researcher_state(bull_cards=bull))
    assert "UNIQUE_BULL_CLAIM" in captured["prompt"]


def test_single_round_bull_prompt_omits_own_prior():
    # P0-2 single round: bull has no prior own cards; the prompt must not carry a
    # self "Your cards so far" block (no consumer), keeping the injected prompt lean.
    turn = ResearcherTurn(argument="bull", cards=[_card(1)])
    llm, captured = _researcher_llm(turn)
    with mock.patch.object(debate, "max_debate_rounds", lambda: 1):
        create_bull_researcher(llm)(_researcher_state())
    assert "Your cards so far" not in captured["prompt"]
