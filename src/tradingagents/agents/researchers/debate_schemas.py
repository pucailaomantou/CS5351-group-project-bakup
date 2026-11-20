"""Idea-card schemas for the two-phase research debate (D3 / FR-01).

These types belong to the research-debate feature and live with the researchers
that produce and consume them, rather than in the shared ``agents.schemas``
module (owned separately). The card is the unit both debate sides and the
Research Manager reason over, so it always carries a claim, its supporting
evidence, its stance and its uncertainty.

Moved here unchanged from ``agents.schemas``; field names, types, constraints
and behaviour are identical.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# Osborn's four rules, as the brainstorming guidance the cards are produced
# under. Keys are the stable tags a card may cite; the values are the wording
# shown to the model.
OSBORN_RULES: dict[str, str] = {
    "defer_judgement": (
        "Defer judgement: propose ideas without rejecting them up front; "
        "critique belongs to the adjudication phase, not generation."
    ),
    "pursue_quantity": (
        "Pursue quantity: the more ideas, the more likely a strong one; do not "
        "stop at the first acceptable claim."
    ),
    "build_on_others": (
        "Build on others: extend or strengthen a useful idea already on the "
        "table (including the opponent's) instead of only inventing anew."
    ),
    "combine_and_improve": (
        "Combine and improve: merge related ideas and refine them into a "
        "stronger, more specific claim."
    ),
}


class DebateStance(StrEnum):
    """A card's direction: which way it argues."""

    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"


class IdeaCard(BaseModel):
    """One idea produced by a side during the generation phase.

    Every card the Research Manager weighs carries the four fields FR-01
    requires: ``claim``, ``evidence``, ``stance`` and ``uncertainty``. ``id``
    is the stable handle the Research Manager cites; ``osborn_rule`` records
    which brainstorming rule produced it (defer judgement, pursue quantity,
    build on others, combine and improve); ``builds_on`` lists the card ids it
    extends, so the debate trace shows how ideas developed.
    """

    id: str = Field(
        description=(
            "Stable identifier for this card, e.g. 'bull-1', 'bear-2'. The "
            "Research Manager cites it in the rationale."
        ),
    )
    claim: str = Field(
        description="The single idea or assertion this card argues for.",
    )
    evidence: str = Field(
        description="The concrete evidence from the analyst reports that supports the claim.",
    )
    stance: DebateStance = Field(
        description="Which way the card argues: Bullish / Bearish / Neutral.",
    )
    uncertainty: str = Field(
        description=(
            "What would have to be true for the claim to fail, or what is not "
            "yet known. Never leave this empty."
        ),
    )
    osborn_rule: Literal[
        "defer_judgement", "pursue_quantity", "build_on_others", "combine_and_improve"
    ] = Field(
        default="defer_judgement",
        description=(
            "Which Osborn rule produced this card: defer_judgement, "
            "pursue_quantity, build_on_others, or combine_and_improve."
        ),
    )
    builds_on: list[str] = Field(
        default_factory=list,
        description="Card ids (own or the opponent's) this idea extends or combines.",
    )


class IdeaCardSet(BaseModel):
    """The cards one side produces in one generation turn."""

    cards: list[IdeaCard] = Field(
        description="One or more idea cards produced this turn under Osborn's rules.",
    )


class ResearcherTurn(BaseModel):
    """One researcher's full turn in a single model call.

    The prosaic debate argument the rest of the system already consumes and the
    structured idea cards the Research Manager weighs are produced together, so
    a Bull/Bear turn costs one generation call instead of two. ``argument`` is
    the natural-language case (the same shape the prose-only path emitted);
    ``cards`` are the Osborn idea cards for this turn.
    """

    argument: str = Field(
        description=(
            "Your full natural-language argument for this turn, in the same "
            "style and depth as a free-text debate reply. Write complete, "
            "evidence-grounded prose; do not merely restate the cards."
        ),
    )
    cards: list[IdeaCard] = Field(
        description=(
            "One or more idea cards produced this turn under Osborn's four "
            "rules, summarising the strongest points of the argument."
        ),
    )


def render_idea_cards(cards: list) -> str:
    """Render a side's cards to compact markdown for the debate history and report.

    Accepts either ``IdeaCard`` instances or their JSON dict form, since cards
    live in state as dicts but are rendered here for prompts and reports.
    """
    if not cards:
        return "(no idea cards)"
    lines = []
    for card in cards:
        if isinstance(card, dict):
            cid = card.get("id", "")
            stance = card.get("stance", "")
            rule = card.get("osborn_rule", "")
            builds_on = card.get("builds_on") or []
            claim = card.get("claim", "")
            evidence = card.get("evidence", "")
            uncertainty = card.get("uncertainty", "")
        else:
            cid = card.id
            stance = card.stance.value
            rule = card.osborn_rule
            builds_on = card.builds_on or []
            claim = card.claim
            evidence = card.evidence
            uncertainty = card.uncertainty
        builds = f" (builds on: {', '.join(builds_on)})" if builds_on else ""
        lines.append(
            f"- [{cid}] ({stance}, {rule}){builds} "
            f"**Claim**: {claim} | **Evidence**: {evidence} | "
            f"**Uncertainty**: {uncertainty}"
        )
    return "\n".join(lines)


def card_to_dict(card: IdeaCard) -> dict:
    """A JSON-serialisable copy of a card, for the saved debate record."""
    return {
        "id": card.id,
        "claim": card.claim,
        "evidence": card.evidence,
        "stance": card.stance.value,
        "uncertainty": card.uncertainty,
        "osborn_rule": card.osborn_rule,
        "builds_on": list(card.builds_on),
    }
