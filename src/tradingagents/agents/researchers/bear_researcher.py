from tradingagents.agents.context import (
    get_instrument_context_from_state,
    get_language_instruction,
    opponent_argument_or_opening,
    report_or_absent,
)
from tradingagents.agents.researchers.debate import (
    CONVERGED,
    MAX_ROUNDS,
    _round_converged,
    bind_turn_schema,
    build_osborn_instructions,
    generate_turn,
    max_debate_rounds,
    render_prior_cards_block,
)


def create_bear_researcher(llm):
    turn_llm = bind_turn_schema(llm, "bear")

    def _last_bull_block(history: str, raw_current: str, opening_marker: str) -> str:
        """The 'Last bull argument' section, or '' when it duplicates ``history``.

        ``raw_current`` is the immediately preceding Bull turn (no marker); the
        turn that produced it already appended the same text to ``history``, so
        re-sending it under a second heading duplicates it verbatim. When it is
        already contained in ``history`` we omit the duplicate. When it is absent
        (a bare state whose history was not maintained) we keep it. When the bull
        has not spoken yet we keep the explicit opening marker so the Bear still
        receives the 'not spoken yet' signal.
        """
        resp = (raw_current or "").strip()
        if resp:
            if resp in history:
                return ""
            return f"\nLast bull argument: {resp}"
        return f"\nLast bull argument: {opening_marker}"

    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        raw_current_response = investment_debate_state.get("current_response", "")
        current_response = opponent_argument_or_opening(raw_current_response, "bull analyst")
        market_research_report = report_or_absent(state["market_report"], "market")
        sentiment_report = report_or_absent(state["sentiment_report"], "sentiment")
        news_report = report_or_absent(state["news_report"], "news")
        fundamentals_report = report_or_absent(state["fundamentals_report"], "fundamentals")
        instrument_context = get_instrument_context_from_state(state)
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )

        bull_cards = investment_debate_state.get("bull_idea_cards", []) or []
        bear_cards = investment_debate_state.get("bear_idea_cards", []) or []
        prior_own = list(bear_cards)
        prior_opp = list(bull_cards)
        round_index = investment_debate_state.get("count", 0) // 2 + 1
        # P0-2: emit prior-card context only when a downstream consumer needs it.
        prior_block = render_prior_cards_block(
            prior_own, prior_opp, side_label_own="bear", side_label_opp="bull"
        )
        prior_section = f"\n{prior_block}" if prior_block else ""
        last_bull_section = _last_bull_block(history, raw_current_response, current_response)

        prompt = f"""You are a Bear Analyst making the case against investing in the {target_label}. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:

- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

In this same turn you also produce structured idea cards under Osborn's four brainstorming rules, so the Research Manager can weigh your case as discrete cards alongside your prose.

{build_osborn_instructions()}

Each card needs a claim, the concrete evidence for it, its stance (Bearish), what would make it fail (uncertainty), and which rule produced it. Do not judge or discard ideas yet; that is the Research Manager's job in the adjudication phase. Tag every card's osborn_rule with exactly one of the four tags and use a spread of them (do not tag every card defer_judgement). In later rounds, prefer build_on_others and combine_and_improve, citing the ids you extend in builds_on.

Resources available:

{instrument_context}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}{last_bull_section}{prior_section}
Use this information to deliver a compelling bear argument, refute the bull's claims, and capture your strongest points as idea cards.
""" + get_language_instruction()

        argument_text, new_cards, turn_status = generate_turn(
            turn_llm, prompt, "bear", round_index, prior_own, prior_opp
        )
        if argument_text is None:
            # Binding unavailable BEFORE any call: exactly one plain prose call.
            # (A post-call parse failure returns salvaged text instead of None,
            # so this branch is not entered once a model call was already made.)
            argument_text = llm.invoke(prompt).content
            new_cards = []

        argument = f"Bear Analyst: {argument_text}"
        all_bear_cards = bear_cards + new_cards

        # --- Close the round: per-round trace + convergence (FR-02) ----------
        # The bear speaks second each round, so this turn closes round
        # ``round_index``. The trace records what each side *added* this round;
        # the debate has converged when neither side added a claim it had not
        # already made in the previous round.
        prev_rounds = list(investment_debate_state.get("debate_rounds", []) or [])
        bull_added = list(investment_debate_state.get("pending_bull_cards", []) or [])
        this_round = {
            "round": round_index,
            "bull_cards": bull_added,
            "bear_cards": list(new_cards),
        }
        prev_bull_added = prev_rounds[-1].get("bull_cards", []) if prev_rounds else []
        prev_bear_added = prev_rounds[-1].get("bear_cards", []) if prev_rounds else []
        converged = bool(prev_rounds) and _round_converged(this_round["bull_cards"], prev_bull_added) \
            and _round_converged(this_round["bear_cards"], prev_bear_added)

        rounds = prev_rounds + [this_round]
        if converged:
            termination_reason = CONVERGED
            convergence_rounds = round_index
        else:
            cap = max_debate_rounds()
            if round_index >= cap:
                termination_reason = MAX_ROUNDS
                convergence_rounds = None
            else:
                termination_reason = investment_debate_state.get("termination_reason", "")
                convergence_rounds = investment_debate_state.get("convergence_rounds")

        new_investment_debate_state = {
            **investment_debate_state,
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
            "bull_idea_cards": bull_cards,
            "bear_idea_cards": all_bear_cards,
            "debate_rounds": rounds,
            "converged": bool(converged),
            "termination_reason": termination_reason,
            "convergence_rounds": convergence_rounds,
            "pending_bull_cards": [],
            "last_turn_status": {**investment_debate_state.get("last_turn_status", {}), "bear": turn_status},
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
