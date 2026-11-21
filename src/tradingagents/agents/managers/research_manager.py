"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

import re

from tradingagents.agents import structured_capture
from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.researchers.debate import (
    CONVERGED,
    MAX_ROUNDS,
    _raw_text_from_result,
    build_debate_record,
    max_debate_rounds,
)
from tradingagents.agents.researchers.debate_schemas import render_idea_cards
from tradingagents.agents.schemas import (
    PortfolioRating,
    ResearchPlan,
    render_research_plan,
)
from tradingagents.agents.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
)


def _render_cards_for_manager(cards: list) -> str:
    if not cards:
        return "(this side produced no structured idea cards; rely on its prose history)"
    return render_idea_cards(cards)


def _card_ids(cards: list) -> list[str]:
    ids = []
    for card in cards or []:
        cid = card.get("id") if isinstance(card, dict) else getattr(card, "id", None)
        if cid:
            ids.append(cid)
    return ids


def _bind_plan_with_raw(llm, agent_name: str):
    """Bind ``ResearchPlan`` with ``include_raw=True`` so a parse failure is salvageable.

    Falls back to a plain structured bind (no raw) if the provider rejects
    ``include_raw``, and to ``None`` (free-text path) if structured output is
    unsupported at all — mirroring ``structured.bind_structured``.
    """
    try:
        return llm.with_structured_output(ResearchPlan, include_raw=True)
    except TypeError:
        return bind_structured(llm, ResearchPlan, agent_name)
    except (NotImplementedError, AttributeError):
        return bind_structured(llm, ResearchPlan, agent_name)


_RATING_TIERS = {r.value.lower() for r in PortfolioRating}
_LABEL_WORDS = ("recommendation", "rating")


def _raw_recommendation(text: str) -> str | None:
    """The tier on the plan's recommendation/rating line, or ``None`` if absent.

    A valid RM plan carries its call on a labelled line. The RM's own rendered
    output uses ``**Recommendation**: X``, while a free-text reply (and the
    decision-style text the system's rating parser reads) may use ``**Rating**: X``;
    both are legitimate shapes, so a whole-word tier on a line carrying either
    label is accepted. Prose that merely mentions a rating word is not.
    """
    for line in (text or "").splitlines():
        low = line.lower()
        if not any(w in low for w in _LABEL_WORDS):
            continue
        for tier in _RATING_TIERS:
            if re.search(rf"\b{re.escape(tier)}\b", low):
                return tier
    return None


def _raw_plan_usable(raw: str, card_ids: list[str]) -> bool:
    """Whether a plan text satisfies the RM output contract (no heavy parsing).

    Requires: a valid tier on a recommendation/rating line; a non-empty rationale
    once that labelled line is removed (the contract says non-empty, so no
    invented length threshold); and, when idea cards exist, at least one card id
    cited. A non-empty blob alone is NOT sufficient.
    """
    text = (raw or "").strip()
    if not text:
        return False
    if _raw_recommendation(text) is None:
        return False
    residual = "\n".join(
        line for line in text.splitlines()
        if not any(w in line.lower() for w in _LABEL_WORDS) and line.strip()
    )
    if not residual.strip():
        return False
    return not card_ids or any(cid and cid in text for cid in card_ids)


def _invoke_plan_one_call(structured_llm, plain_llm, prompt, agent_name: str,
                          card_ids: list[str]) -> str:
    """Produce the investment plan with AT MOST ONE model call in normal paths.

    Contract-preserving single-call path:

    - ``structured_llm is None`` (unsupported before any call): one plain call.
    - Binding present: exactly ONE structured call is attempted here.
        * parsed ``ResearchPlan`` -> rendered markdown (unchanged contract).
        * parse missed but the raw completion is *usable* per ``_raw_plan_usable``
          -> reuse that raw text, WITHOUT a second model call.
        * raw missing or not usable -> ONE plain ``plain_llm.invoke`` fallback.
    - The structured call raising is treated like a parse miss: ONE plain
      fallback is attempted (a call was already made; we do not loop).
    - If the plain fallback ALSO fails (raises) or returns no usable plan, the
      error propagates / a ``RuntimeError`` is raised. We NEVER return a
      placeholder string that would let a run with no real adjudication look
      successful.

    Observability (``structured_capture``): a present binding records one
    ``structured_attempts``; a parsed result records ``structured_success``; a
    raw-reuse or a plain fallback records ``fallback_attempts`` (raw-reuse is NOT
    counted as a parsed success). Plain fallback means an extra model call; with
    raw-reuse there is no extra call.
    """
    rec = structured_capture.active()
    if structured_llm is None:
        if rec is not None:
            rec.record_fallback(agent_name)
        return _plain_fallback(plain_llm, prompt, card_ids)

    if rec is not None:
        rec.record_attempt(agent_name)
    try:
        result = structured_llm.invoke(prompt)
    except Exception:
        result = None  # treated as a parse miss; one plain fallback below

    parsed = result.get("parsed") if isinstance(result, dict) else result
    if isinstance(parsed, ResearchPlan):
        if rec is not None:
            rec.record_success(agent_name)
        return render_research_plan(parsed)

    raw = _raw_text_from_result(result)
    if isinstance(raw, str) and _raw_plan_usable(raw, card_ids):
        if rec is not None:
            rec.record_fallback(agent_name)  # reused raw, NOT a parsed success
        return raw.strip()

    # No usable structured/raw result: exactly one plain model call.
    if rec is not None:
        rec.record_fallback(agent_name)
    return _plain_fallback(plain_llm, prompt, card_ids)


def _plain_fallback(plain_llm, prompt, card_ids: list[str]) -> str:
    """One plain call validated with the SAME contract as raw reuse.

    The plain free-text reply must satisfy ``_raw_plan_usable`` (valid
    recommendation + non-trivial rationale + a cited card id when cards exist);
    a bare "Recommendation: Buy" is NOT a complete adjudication. On failure this
    raises — no placeholder, so a run with no real plan cannot look successful.
    """
    resp = plain_llm.invoke(prompt)
    content = getattr(resp, "content", resp)
    text = content if isinstance(content, str) else ""
    if not _raw_plan_usable(text, card_ids):
        raise RuntimeError(
            "Research Manager produced no usable investment plan "
            "(fallback failed the recommendation/rationale/citation contract)."
        )
    return text


def create_research_manager(llm):
    structured_llm = _bind_plan_with_raw(llm, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")

        bull_cards = investment_debate_state.get("bull_idea_cards", []) or []
        bear_cards = investment_debate_state.get("bear_idea_cards", []) or []
        cap = max_debate_rounds()
        rounds = investment_debate_state.get("debate_rounds", []) or []

        bull_block = _render_cards_for_manager(bull_cards)
        bear_block = _render_cards_for_manager(bear_cards)
        have_cards = bool(bull_cards or bear_cards)
        citation_rule = (
            "Cite the ids of the specific idea cards (e.g. bull-1, bear-2) that "
            "decided your call, and say which side's cards held up better. "
            "Reference at least one card id in the rationale."
            if have_cards
            else "No idea cards were produced this run; weigh the prose debate."
        )

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

The debate always contains conflicting arguments; deciding which side is stronger is the job, so conflict alone is not a reason to Hold. Commit to the side with the stronger case, sized by how decisively it wins. Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; do not manufacture a direction to appear decisive. Weigh the bull and bear cases on their merits, independent of which side spoke first or last.

---

**Bull idea cards:**
{bull_block}

**Bear idea cards:**
{bear_block}

**Debate History:**
{history}

## Output

Write these sections, in this order, starting with the recommendation on its own line:

- **Recommendation**: exactly one of Buy / Overweight / Hold / Underweight / Sell
- **Rationale**: which arguments decided it. {citation_rule}
- **Strategic Actions**: concrete steps for the trader, sized against a standard allocation

{NO_EXTERNAL_TOOLS}""" + get_language_instruction()

        investment_plan = _invoke_plan_one_call(
            structured_llm,
            llm,
            prompt,
            "Research Manager",
            _card_ids(bull_cards) + _card_ids(bear_cards),
        )

        # --- Record how the debate terminated (FR-02) ------------------------
        termination_reason = investment_debate_state.get("termination_reason") or ""
        convergence_rounds = investment_debate_state.get("convergence_rounds")
        if termination_reason not in (CONVERGED, MAX_ROUNDS):
            # Reached from a debate that recorded no reason (e.g. a bare state
            # or max_debate_rounds == 0). Infer it so the field is never empty.
            # ``convergence_rounds`` stays None unless a real round converged;
            # no negative sentinel is ever stored.
            count = investment_debate_state.get("count", 0)
            rounds_ran = count // 2
            if rounds_ran == 0 or rounds_ran >= cap:
                termination_reason = MAX_ROUNDS
                convergence_rounds = None
            else:
                termination_reason = CONVERGED
                convergence_rounds = rounds_ran

        cited = [cid for cid in (_card_ids(bull_cards) + _card_ids(bear_cards))
                 if cid and cid in investment_plan]
        debate_record = build_debate_record(
            bull_cards=bull_cards,
            bear_cards=bear_cards,
            rounds=rounds,
            termination_reason=termination_reason,
            convergence_rounds=convergence_rounds,
            max_rounds=cap,
            rationale_citations=cited,
            turn_status=investment_debate_state.get("last_turn_status", {}),
        )

        new_investment_debate_state = {
            **investment_debate_state,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
            "bull_idea_cards": bull_cards,
            "bear_idea_cards": bear_cards,
            "debate_rounds": rounds,
            "convergence_rounds": convergence_rounds,
            "termination_reason": termination_reason,
            "debate_record": debate_record,
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
