from tradingagents.agents.context import (
    get_instrument_context_from_state,
    get_language_instruction,
    opponent_argument_or_opening,
    report_or_absent,
)
from tradingagents.agents.researchers.debate import (
    bind_turn_schema,
    build_osborn_instructions,
    generate_turn,
    render_prior_cards_block,
)


def create_bull_researcher(llm):
    turn_llm = bind_turn_schema(llm, "bull")

    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = opponent_argument_or_opening(
            investment_debate_state.get("current_response", ""), "bear analyst"
        )
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
        prior_own = list(bull_cards)
        prior_opp = list(bear_cards)
        round_index = investment_debate_state.get("count", 0) // 2 + 1
        # P0-2: emit prior-card context only when a downstream consumer needs it
        # (empty blocks and single-round self-blocks are omitted to save input).
        prior_block = render_prior_cards_block(
            prior_own, prior_opp, side_label_own="bull", side_label_opp="bear"
        )
        prior_section = f"\n{prior_block}" if prior_block else ""

        prompt = f"""You are a Bull Analyst advocating for investing in the {target_label}. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the company's market opportunities, revenue projections, and scalability.
- Competitive Advantages: Emphasize factors like unique products, strong branding, or dominant market positioning.
- Positive Indicators: Use financial health, industry trends, and recent positive news as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.

In this same turn you also produce structured idea cards under Osborn's four brainstorming rules, so the Research Manager can weigh your case as discrete cards alongside your prose.

{build_osborn_instructions()}

Each card needs a claim, the concrete evidence for it, its stance (Bullish), what would make it fail (uncertainty), and which rule produced it. Do not judge or discard ideas yet; that is the Research Manager's job in the adjudication phase. Tag every card's osborn_rule with exactly one of the four tags and use a spread of them (do not tag every card defer_judgement). In later rounds, prefer build_on_others and combine_and_improve, citing the ids you extend in builds_on.

Resources available:
{instrument_context}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bear argument: {current_response}{prior_section}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and capture your strongest points as idea cards.
""" + get_language_instruction()

        argument_text, new_cards, turn_status = generate_turn(
            turn_llm, prompt, "bull", round_index, prior_own, prior_opp
        )
        if argument_text is None:
            # Binding unavailable BEFORE any call: exactly one plain prose call.
            # (A post-call parse failure returns salvaged text instead of None,
            # so this branch is not entered once a model call was already made.)
            argument_text = llm.invoke(prompt).content
            new_cards = []

        argument = f"Bull Analyst: {argument_text}"
        all_bull_cards = bull_cards + new_cards

        new_investment_debate_state = {
            **investment_debate_state,
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
            "bull_idea_cards": all_bull_cards,
            "bear_idea_cards": bear_cards,
            "last_turn_status": {**investment_debate_state.get("last_turn_status", {}), "bull": turn_status},
            # The bear closes this round; hand it the cards added this turn so
            # it can record the round and judge convergence.
            "pending_bull_cards": new_cards,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
