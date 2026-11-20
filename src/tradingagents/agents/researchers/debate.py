"""Two-phase research debate: Osborn idea cards, then adjudication (D3 / FR-01, FR-02).

The research debate used to be free-form prose: the bull and bear traded
arguments and the Research Manager read the transcript. This module adds the
structure the manager needs to actually weigh arguments:

Phase 1 - generation. Each side produces *idea cards* under Osborn's four
brainstorming rules (defer judgement, pursue quantity, build on others,
combine and improve). A card carries a claim, its supporting evidence, a
stance and its uncertainty. Cards are the unit the manager reasons over.

Phase 2 - adjudication. The Research Manager weighs the cards and cites card
ids in its rationale.

The prose history each side already produced is kept unchanged: cards are
layered on top, so existing display, reporting and memory-log paths keep
working. When a provider cannot produce structured output, generation falls
back to the prose only and the trace records that cards were unavailable.

The debate is bounded by ``max_debate_rounds``. Convergence is judged
deterministically (see ``_round_converged``) so a run can record *why* it
stopped and after how many rounds, which is what Before/After evaluation
needs to compare.
"""

from __future__ import annotations

import logging
from typing import Any

from tradingagents.agents.researchers.debate_schemas import (
    OSBORN_RULES,
    IdeaCard,
    IdeaCardSet,
    ResearcherTurn,
    card_to_dict,
)
from tradingagents.agents.structured import bind_structured

logger = logging.getLogger(__name__)

# Termination reasons recorded in investment_debate_state["termination_reason"].
CONVERGED = "converged"
MAX_ROUNDS = "max_rounds"

PHASE_GENERATION = "generation"
PHASE_ADJUDICATION = "adjudication"

# Round 2 cost control (P0-1). The card count and field lengths are capped at
# the GENERATION stage (prompt guidance) and enforced again deterministically in
# normalise_cards as a safety net, so a run never exceeds these bounds even if
# the model ignores the instruction. FR-01 needs >=1 card per side with
# claim/evidence/stance/uncertainty intact; the caps keep those fields meaningful
# for the Research Manager rather than deleting them.
MAX_CARDS_PER_SIDE = 5
MAX_CLAIM_CHARS = 240
MAX_EVIDENCE_CHARS = 400
MAX_UNCERTAINTY_CHARS = 240


def _clip(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars, marking a cut so it is not mistaken for complete."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def build_osborn_instructions() -> str:
    """The four Osborn rules rendered as prompt guidance for the generation phase."""
    lines = ["Produce your idea cards under Osborn's four brainstorming rules:"]
    for tag, text in OSBORN_RULES.items():
        lines.append(f"- ({tag}) {text}")
    lines.append(
        f"Produce at most {MAX_CARDS_PER_SIDE} cards, choosing your strongest, most "
        "distinct points (do not pad with near-duplicates). Keep each card concise: "
        f"claim <= {MAX_CLAIM_CHARS} chars, evidence <= {MAX_EVIDENCE_CHARS}, "
        f"uncertainty <= {MAX_UNCERTAINTY_CHARS}."
    )
    return "\n".join(lines)


def _existing_ids(*card_lists: list) -> set[str]:
    ids: set[str] = set()
    for cards in card_lists:
        for card in cards or []:
            cid = card.get("id") if isinstance(card, dict) else getattr(card, "id", None)
            if cid:
                ids.add(cid)
    return ids


# How convergence is decided, recorded verbatim so a reader (or a Before/After
# evaluator) knows the rule the numbers came from rather than having to infer it.
CONVERGENCE_METHOD = (
    "structural_no_new_claims: a round converges when both sides' new cards add "
    "no (stance, claim) pair absent from the previous round; deterministic, no "
    "LLM call; checked once per completed bull+bear round."
)


def osborn_rules_used(*card_lists: list) -> list[str]:
    """Which of the four Osborn rules the produced cards actually cite.

    Returns the rule tags that appear on at least one card, in the canonical
    order. Empty when no cards were produced (structured output unavailable).
    """
    seen: set[str] = set()
    for cards in card_lists:
        for card in cards or []:
            rule = card.get("osborn_rule") if isinstance(card, dict) else getattr(card, "osborn_rule", None)
            if rule:
                seen.add(str(rule))
    return [tag for tag in OSBORN_RULES if tag in seen]


def bind_turn_schema(llm: Any, side: str) -> Any | None:
    """Bind ``ResearcherTurn`` structured output for one side, or ``None`` if unsupported.

    ``include_raw=True`` is requested so a single call that fails to *parse*
    still yields the model's raw text: the caller can keep that argument
    instead of spending a second generation call to recover it. Providers that
    do not accept ``include_raw`` fall back to a plain bind.
    """
    agent_name = f"{side.title()} Researcher"
    try:
        return llm.with_structured_output(ResearcherTurn, include_raw=True)
    except TypeError:
        # Older/limited bindings may not accept include_raw; without it a parse
        # failure loses the raw text but still must not trigger a second call.
        return bind_structured(llm, ResearcherTurn, agent_name)
    except (NotImplementedError, AttributeError) as exc:
        # Provider cannot do structured output at all -> one plain prose call.
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


def _raw_text_from_result(result: Any) -> str | None:
    """Best-effort extraction of the model's raw text from a structured result.

    Handles the ``include_raw`` envelope (``{"raw": AIMessage, ...}``) and a bare
    string/message. Returns ``None`` when nothing usable is present.
    """
    if isinstance(result, dict):
        raw = result.get("raw")
        parsed = result.get("parsed")
        if isinstance(parsed, ResearcherTurn) and (parsed.argument or "").strip():
            return parsed.argument
        return _raw_text_from_result(raw)
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    return None


def generate_turn(
    structured_llm: Any | None,
    prompt: str,
    side: str,
    round_index: int,
    prior_own_cards: list,
    prior_opponent_cards: list,
) -> tuple[str | None, list[dict], str]:
    """Produce a researcher's argument and idea cards in ONE model call.

    Returns ``(argument, cards, status)``. The *model call* accounting:

    - ``structured_llm is None`` (binding unavailable BEFORE any call): returns
      ``(None, [], "no_structured")`` — the caller makes exactly one plain prose
      call. No structured attempt is made.
    - Binding available: **exactly one** structured call is attempted here.
        * Parsed a valid ``ResearcherTurn`` with non-empty argument →
          ``(argument, cards, "ok")`` — one call, caller does not call again.
        * A model response came back but had no parseable argument, yet carried
          raw text (the real-provider parse-failure case: ``include_raw`` gives
          ``{"raw": AIMessage, "parsed": None}``) → ``(salvaged_text, [],
          "structured_failed")`` — one call, caller does not call again.
        * The call returned a value with **no usable text at all** (e.g. an
          auto-mocked ``with_structured_output`` exposing no model message):
          no real text was produced, so return ``(None, [], "no_structured_result")``
          — the caller makes exactly one plain prose call. This restores the
          plain-text path for stubs/mocks without risking a second paid call on
          a real provider (whose raw text is always present).
        * The structured call **raised**: a (possibly billable) call was already
          made, so we must NOT call again. Return a placeholder argument with
          ``"structured_failed"`` so the caller keeps its single-call guarantee.

    The third element is retained for diagnostics (``last_turn_status``).
    """
    agent_name = f"{side.title()} Researcher"
    if structured_llm is None:
        return None, [], "no_structured"

    try:
        result = structured_llm.invoke(prompt)
    except Exception as exc:
        # A call was attempted and failed after transmission: never re-call.
        logger.warning(
            "%s: structured-output invocation failed (%s); keeping a placeholder argument "
            "(no second model call)", agent_name, exc,
        )
        return "(argument unavailable: structured call failed)", [], "structured_failed"

    # Normalise the possible result shapes to (parsed_turn, raw_text).
    if isinstance(result, ResearcherTurn):
        parsed, raw_text = result, result.argument
    elif isinstance(result, dict):
        parsed = result.get("parsed") if isinstance(result.get("parsed"), ResearcherTurn) else None
        raw_text = _raw_text_from_result(result)
    else:
        parsed, raw_text = None, _raw_text_from_result(result)

    if isinstance(parsed, ResearcherTurn):
        argument = (parsed.argument or "").strip()
        if argument:
            cards = normalise_cards(parsed.cards, side, round_index, prior_own_cards, prior_opponent_cards)
            return argument, cards, "ok"
        # Parsed, but no argument text: salvage raw text if any, else no text.
        fallback = (raw_text or "").strip()
        if fallback:
            return fallback, [], "structured_failed"
        return None, [], "no_structured_result"

    fallback = (raw_text or "").strip()
    if fallback:
        # Real-provider parse failure: raw text present -> keep it, no re-call.
        return fallback, [], "structured_failed"
    # No usable text was produced at all (stub / empty response): signal the
    # caller to make exactly one plain prose call.
    return None, [], "no_structured_result"


def normalise_cards(
    result: Any,
    side: str,
    round_index: int,
    prior_own_cards: list,
    prior_opponent_cards: list,
) -> list[dict]:
    """Turn parsed idea cards into JSON-safe dicts with unique, stable ids.

    Two passes:

    1. Assign deterministic ids ``<side>-<round>-<n>`` to every card in this
       batch, building the full set of ids that may be referenced.
    2. Resolve each card's ``builds_on`` against prior cards AND the other
       cards in this same batch. A valid same-batch link (the model citing an
       id it emitted this turn) is kept; an invalid reference is dropped.

    ``result`` may be an ``IdeaCardSet``, a ``ResearcherTurn``, or a list of
    ``IdeaCard``. Only the card list is normalised here.
    """
    if isinstance(result, IdeaCardSet):
        model_cards: list[IdeaCard] = list(result.cards)
    elif isinstance(result, ResearcherTurn):
        model_cards = list(result.cards)
    elif isinstance(result, list):
        model_cards = [c for c in result if isinstance(c, IdeaCard)]
    else:
        return []

    # Cap at the generation bound (P0-1). The prompt asks for at most this many;
    # this is the deterministic safety net if the model returns more. Keeping the
    # first N preserves the model's own ordering (strongest first, typically).
    if len(model_cards) > MAX_CARDS_PER_SIDE:
        model_cards = model_cards[:MAX_CARDS_PER_SIDE]

    # Pass 1: assign ids and remember both the prior ids and this batch's ids,
    # along with the model's raw (pre-normalisation) id -> new id mapping so a
    # same-batch citation by the model's own id can be translated.
    prior_ids = _existing_ids(prior_own_cards, prior_opponent_cards)
    batch_ids: list[str] = []
    raw_to_new: dict[str, str] = {}
    for index, card in enumerate(model_cards, start=1):
        new_id = f"{side}-{round_index}-{index}"
        batch_ids.append(new_id)
        raw_id = (card.id or "").strip()
        if raw_id:
            raw_to_new.setdefault(raw_id, new_id)
    referencable = prior_ids | set(batch_ids)

    # Pass 2: resolve build links, keeping prior ids, this batch's new ids, and
    # the model's own raw ids (translated to their new id). Drop all else.
    cards: list[dict] = []
    for new_id, card in zip(batch_ids, model_cards, strict=True):
        resolved: list[str] = []
        for ref in card.builds_on or []:
            ref = str(ref).strip()
            if not ref or ref == new_id:
                continue
            target = raw_to_new.get(ref, ref)
            if target in referencable and target != new_id and target not in resolved:
                resolved.append(target)
        rendered = card_to_dict(card)
        rendered["id"] = new_id
        rendered["builds_on"] = resolved
        # Clip field lengths (P0-1 safety net); the required fields stay present
        # and non-empty, only over-long text is trimmed.
        rendered["claim"] = _clip(rendered.get("claim", ""), MAX_CLAIM_CHARS)
        rendered["evidence"] = _clip(rendered.get("evidence", ""), MAX_EVIDENCE_CHARS)
        rendered["uncertainty"] = _clip(rendered.get("uncertainty", ""), MAX_UNCERTAINTY_CHARS)
        cards.append(rendered)
    return cards


def _stance_signature(cards: list) -> frozenset:
    """A comparison key for one side's cards: the *set* of (stance, claim) pairs.

    Used by convergence: a round is "new" when it adds a claim the previous
    round did not carry. Normalising case/whitespace stops trivial rewording
    from reading as progress. A set (not a list) is used so a model repeating
    the same claim twice in one round does not read as a different position and
    block convergence.

    Convergence is deliberately compared round-to-round (the previous completed
    round), not against a cumulative union: because the graph routes to the
    Research Manager the moment a round converges, a side can never "repeat in
    round N, add something new in round N+1" -- it would already have stopped
    at round N. The audit's repeat-then-new false positive is therefore not
    reachable, and the simpler consecutive comparison is kept.
    """
    signature = set()
    for card in cards or []:
        if isinstance(card, dict):
            claim = card.get("claim", "")
            stance = card.get("stance", "")
        else:
            claim = getattr(card, "claim", "")
            stance = getattr(card, "stance", "")
        signature.add((str(stance), " ".join(str(claim).lower().split())))
    return frozenset(signature)


def _round_converged(current_side_cards: list, previous_side_cards: list) -> bool:
    """Whether one side's newest cards add nothing over its previous ones.

    Convergence is structural, not a quality judgement: if a side's latest
    round introduces no claim it did not already make, further rounds are not
    changing its position. This is deterministic and needs no model call, so
    the termination reason is never an LLM's opinion.

    Empty-card safety: a side with NO cards in either the current or the
    previous round is NOT considered converged. Two empty sets comparing equal
    must never be read as "the debate settled" -- missing cards (e.g. a
    structured-output fallback) carry no evidence of a position, whereas
    convergence means a *stated* position stopped changing. Requiring valid
    cards on both sides of both rounds makes the empty==empty case converge to
    ``False`` by construction, independent of any earlier short-circuit.
    """
    if not current_side_cards or not previous_side_cards:
        return False
    return _stance_signature(current_side_cards) == _stance_signature(previous_side_cards)


def build_debate_record(
    bull_cards: list,
    bear_cards: list,
    rounds: list,
    termination_reason: str,
    convergence_rounds: int | None,
    max_rounds: int,
    rationale_citations: list | None = None,
    turn_status: dict | None = None,
) -> dict:
    """Assemble the structured, JSON-serialisable debate record (FR-01, FR-02).

    ``rounds`` is the per-round trace built during the debate. ``convergence_rounds``
    is the round the debate converged at, or ``None`` when it did not converge
    (it hit ``max_rounds``); ``None`` serialises as JSON ``null`` and is never a
    misleading negative. The record also states the convergence method actually
    used, which Osborn rules the cards exercised, and the last turn's generation
    path per side (for fallback diagnostics).
    """
    return {
        "schema_version": 1,
        "phases": [PHASE_GENERATION, PHASE_ADJUDICATION],
        "osborn_rules": list(OSBORN_RULES.keys()),
        "osborn_rules_used": osborn_rules_used(bull_cards, bear_cards),
        "bull_idea_cards": [card_to_dict(c) if isinstance(c, IdeaCard) else dict(c) for c in bull_cards or []],
        "bear_idea_cards": [card_to_dict(c) if isinstance(c, IdeaCard) else dict(c) for c in bear_cards or []],
        "rounds": rounds or [],
        "max_rounds": max_rounds,
        "termination_reason": termination_reason,
        "convergence_rounds": convergence_rounds,
        "convergence_method": CONVERGENCE_METHOD,
        "rationale_citations": list(rationale_citations or []),
        "turn_status": dict(turn_status or {}),
    }


def max_debate_rounds() -> int:
    """The configured cap on debate rounds (each round is one bull + one bear turn)."""
    from tradingagents.dataflows.config import get_config
    try:
        value = get_config().get("max_debate_rounds")
    except Exception:
        value = None
    return value if isinstance(value, int) and value >= 0 else 1


def render_prior_cards_block(own_cards: list, opponent_cards: list, *, side_label_own: str, side_label_opp: str) -> str:
    """The prior-card context block for a researcher prompt (P0-2), or "" when unneeded.

    Round 2 input-cost control: a block is emitted only when it carries usable
    cards for a downstream consumer.

    - Empty prior blocks are omitted entirely (the old "(none yet this debate)"
      placeholder was pure prompt cost with no information).
    - The *own-side* prior block is omitted when ``max_debate_rounds() <= 1``:
      with a single round there is no later turn of this side that would read
      it, so injecting a side's own earlier cards serves no consumer. The
      opponent block is still emitted when non-empty, because the same-round
      responder (e.g. bear reading bull's round-1 cards) genuinely consumes it.
    - The Research Manager's final adjudication reads the stored
      ``bull_idea_cards`` / ``bear_idea_cards`` directly, so omitting this prompt
      block never removes cards the RM needs.

    Returns the assembled block (possibly "") for the caller to append.
    """
    from tradingagents.agents.researchers.debate_schemas import render_idea_cards

    parts: list[str] = []
    own = list(own_cards or [])
    opp = list(opponent_cards or [])
    if own and max_debate_rounds() > 1:
        parts.append(f"Your cards so far: {render_idea_cards(own)}")
    if opp:
        parts.append(f"Opponent ({side_label_opp}) cards so far: {render_idea_cards(opp)}")
    return "\n".join(parts)
