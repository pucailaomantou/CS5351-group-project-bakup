from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import TypedDict

# --- Point-in-time input provenance (INV-03) --------------------------------
# Each analyst records, per input it actually received into its model context,
# the real data cutoff ("as-of") of that input. D's deterministic guard reads
# this to judge freshness per input class. This module only records; it never
# decides REVIEW and never sets a freshness threshold.
#
# The reducer is a pure function: it never mutates its arguments, is idempotent,
# commutative and associative, and keeps every distinct fact version (N), so the
# same set of inputs always yields the same sorted output regardless of merge
# order or replay.
_CONFLICT_REASON = "conflict_kept_all"


class InputProvenance(TypedDict):
    """One point-in-time input's provenance. All keys are required."""

    analyst: Annotated[str, "Analyst that received this input"]
    tool: Annotated[str, "Tool/input source identifier"]
    call_id: Annotated[str, "Tool call correlation id (LangGraph tool_call_id)"]
    input_class: Annotated[str, "INV-03 input class this input maps to"]
    period_id: Annotated[str, "Statement period identifier; empty string when not period-scoped"]
    as_of: Annotated[str | None, "Real data cutoff (ISO); None when unknowable, never backfilled"]
    precision: Annotated[str, "Time precision: 'date' | 'datetime' | 'unknown'"]
    semantics: Annotated[str, "What as_of means, e.g. 'latest_trading_row' | 'period_end' | 'filing_date' | 'market_implied_probability' | 'unknown'"]
    evidence: Annotated[str, "Normalized source fragment/tag the value came from"]
    available: Annotated[bool, "True only when data was returned and entered the analyst context"]
    time_reliable: Annotated[bool, "Whether the time source is reliable; not a freshness verdict"]
    missing_reason: Annotated[str, "Empty, or why as_of is unknown/conflicting"]


def _norm_evidence(evidence: str) -> str:
    """Canonical form of ``evidence`` used identically for the signature and output."""
    return " ".join(str(evidence or "").split())


def _as_of_key(as_of: str | None) -> tuple[int, str]:
    """Sortable key that never compares ``None`` with a string."""
    return (0, "") if as_of is None else (1, str(as_of))


def _fact_sig(entry: dict) -> tuple:
    """The fact signature: data facts only.

    Excludes ``time_reliable`` and ``missing_reason`` (derived fields) so that
    re-merging the same facts after conflict normalisation never makes a new
    version (idempotent replay, bounded entry count).
    """
    return (
        entry.get("input_class", ""),
        _as_of_key(entry.get("as_of")),
        entry.get("precision", ""),
        _norm_evidence(entry.get("evidence", "")),
        bool(entry.get("available", False)),
    )


def _identity_key(entry: dict) -> tuple:
    return (
        entry.get("analyst", ""),
        entry.get("call_id", ""),
        entry.get("tool", ""),
        entry.get("semantics", ""),
        entry.get("period_id", ""),
    )


_STRING_FIELDS = ("analyst", "tool", "call_id", "input_class", "period_id",
                  "precision", "semantics", "evidence", "missing_reason")
_BOOL_FIELDS = ("available", "time_reliable")
_PRECISIONS = ("date", "datetime", "unknown")


def _validate_provenance(entry: dict) -> None:
    """Reject a provenance entry with a missing required key or wrong field type.

    A malformed entry must never be normalised by defaults into a would-be valid
    record: it raises instead. This keeps the guard from ever reading a
    silently-coerced provenance.
    """
    required = set(_STRING_FIELDS) | set(_BOOL_FIELDS) | {"as_of"}
    missing = required - set(entry)
    if missing:
        raise ValueError(f"InputProvenance missing required keys: {sorted(missing)}")
    for key in _STRING_FIELDS:
        if not isinstance(entry[key], str):
            raise TypeError(f"InputProvenance[{key!r}] must be str, got {type(entry[key]).__name__}")
    for key in _BOOL_FIELDS:
        if not isinstance(entry[key], bool):
            raise TypeError(f"InputProvenance[{key!r}] must be bool, got {type(entry[key]).__name__}")
    if entry["as_of"] is not None and not isinstance(entry["as_of"], str):
        raise TypeError(f"InputProvenance['as_of'] must be str or None, got {type(entry['as_of']).__name__}")
    if entry["precision"] not in _PRECISIONS:
        raise ValueError(f"InputProvenance['precision'] must be one of {_PRECISIONS}")


def _merge_derived(entries: list[dict]) -> tuple[bool, str]:
    """Conservative join of derived fields for entries sharing identity+fact.

    ``time_reliable`` is AND (any unreliable -> unreliable; never upgrade).
    ``missing_reason`` keeps an existing ``conflict_kept_all``; otherwise a single
    distinct non-empty value is kept and conflicting non-empty values collapse to
    ``conflict_kept_all`` (multiple differing causes are themselves unreliable).
    """
    reliable = all(bool(e.get("time_reliable", False)) for e in entries)
    reasons = {e.get("missing_reason", "") for e in entries}
    if _CONFLICT_REASON in reasons:
        # A preserved conflict marker always means the merged entry is unreliable,
        # regardless of the inputs' own reliability: never let a conflict read reliable.
        reason = _CONFLICT_REASON
        reliable = False
    else:
        nonempty = {r for r in reasons if r}
        if not nonempty:
            reason = ""
        elif len(nonempty) == 1:
            reason = next(iter(nonempty))
        else:
            reason = _CONFLICT_REASON
            reliable = False
    return reliable, reason


def _merge_input_provenance(left: list | None, right: list | None) -> list:
    """Pure, idempotent, commutative, associative merge of provenance entries.

    Groups by identity key, then by fact signature; keeps every distinct fact
    version (N per identity). Derived fields are joined conservatively and a
    conflicting, unreliable group never becomes reliable. The output is fully
    sorted over all fields that can differ, so identical input sets give
    identical output. Inputs are never mutated.
    """
    groups: dict[tuple, dict[tuple, list[dict]]] = {}
    for src in (left or []), (right or []):
        for raw in src:
            entry = dict(raw)  # copy; never mutate caller objects
            _validate_provenance(entry)
            entry["evidence"] = _norm_evidence(entry.get("evidence", ""))
            entry.setdefault("period_id", "")
            groups.setdefault(_identity_key(entry), {}).setdefault(_fact_sig(entry), []).append(entry)

    out: list[dict] = []
    for ident, by_sig in groups.items():
        conflict = len(by_sig) > 1
        for sig, entries in by_sig.items():
            reliable, reason = _merge_derived(entries)
            base = dict(entries[0])
            if conflict:
                # Every conflicting version is unreliable; never silently pass one.
                reliable = False
                reason = _CONFLICT_REASON
            normalized = {
                "analyst": ident[0],
                "call_id": ident[1],
                "tool": ident[2],
                "semantics": ident[3],
                "period_id": ident[4],
                "input_class": sig[0],
                "as_of": base.get("as_of"),
                "precision": base.get("precision", ""),
                "evidence": _norm_evidence(base.get("evidence", "")),
                "available": bool(base.get("available", False)),
                "time_reliable": reliable,
                "missing_reason": reason,
            }
            out.append(normalized)

    out.sort(key=lambda e: (
        e["analyst"], e["call_id"], e["tool"], e["semantics"], e["period_id"],
        e["input_class"], _as_of_key(e["as_of"]), e["precision"], e["evidence"],
        e["available"], e["time_reliable"], e["missing_reason"],
    ))
    return out


# Researcher team state
class InvestDebateState(TypedDict):
    bull_history: Annotated[
        str, "Bullish Conversation history"
    ]
    bear_history: Annotated[
        str, "Bearish Conversation history"
    ]
    history: Annotated[str, "Conversation history"]
    current_response: Annotated[str, "Latest response"]
    count: Annotated[int, "Length of the current conversation"]
    # --- Two-phase structured debate (D3) -----------------------------------
    # Phase 1 accumulates each side's Osborn idea cards; phase 2 is the
    # Research Manager adjudicating from them. These are lists of JSON-safe card
    # dicts (see researchers.debate_schemas.card_to_dict) so the debate record serialises directly.
    bull_idea_cards: Annotated[list, "Bull side idea cards produced under Osborn's rules"]
    bear_idea_cards: Annotated[list, "Bear side idea cards produced under Osborn's rules"]
    # Per-round trace: one entry per completed debate round with both sides' cards.
    debate_rounds: Annotated[list, "Per-round debate trace for the JSON record"]
    # How the debate ended and after how many rounds (FR-02).
    convergence_rounds: Annotated[int | None, "Round at which the debate converged; None when it did not converge (hit the cap)"]
    termination_reason: Annotated[str, "Why the debate stopped: 'converged' or 'max_rounds'"]
    converged: Annotated[bool, "Set when the latest completed round added no new claims on either side"]
    # Cards the bull added in the round currently in progress; the bear closes
    # the round using this plus its own additions, then this is cleared.
    pending_bull_cards: Annotated[list, "Bull cards added in the round currently in progress"]
    # Diagnostic status of each side's latest turn generation path
    # ("ok" / "no_structured" / "structured_failed"), for fallback tracking.
    last_turn_status: Annotated[dict, "Per-side status of the last turn's generation path"]
    # The fully structured record the run saves alongside its prose history.
    debate_record: Annotated[dict, "Structured JSON debate record (phases, cards, rounds, outcome)"]


# Risk management team state
class RiskDebateState(TypedDict):
    aggressive_history: Annotated[
        str, "Aggressive Agent's Conversation history"
    ]
    conservative_history: Annotated[
        str, "Conservative Agent's Conversation history"
    ]
    neutral_history: Annotated[
        str, "Neutral Agent's Conversation history"
    ]
    history: Annotated[str, "Conversation history"]
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[
        str, "Latest response by the aggressive analyst"
    ]
    current_conservative_response: Annotated[
        str, "Latest response by the conservative analyst"
    ]
    current_neutral_response: Annotated[
        str, "Latest response by the neutral analyst"
    ]
    count: Annotated[int, "Length of the current conversation"]


class AgentState(MessagesState):
    company_of_interest: Annotated[str, "Company that we are interested in trading"]
    asset_type: Annotated[str, "Asset type under analysis such as stock or crypto"]
    instrument_context: Annotated[str, "Deterministic ticker identity resolved at run start"]
    trade_date: Annotated[str, "The analysis date; data is served as of it"]

    # research step
    market_report: Annotated[str, "Report from the Market Analyst"]
    sentiment_report: Annotated[str, "Report from the Sentiment Analyst"]
    news_report: Annotated[str, "Report from the News Analyst on company and world news"]
    fundamentals_report: Annotated[str, "Report from the Fundamentals Analyst"]

    # researcher team discussion step
    investment_debate_state: Annotated[
        InvestDebateState, "Current state of the debate on if to invest or not"
    ]
    investment_plan: Annotated[str, "Investment plan from the Research Manager"]

    trader_investment_plan: Annotated[str, "Transaction proposal from the Trader"]

    # risk management team discussion step
    risk_debate_state: Annotated[
        RiskDebateState, "Current state of the debate on evaluating risk"
    ]
    final_trade_decision: Annotated[str, "Final decision from the Portfolio Manager"]
    final_rating: Annotated[str, "The Portfolio Manager's 5-tier rating, or REVIEW when it has none"]
    past_context: Annotated[str, "Memory log context for the Portfolio Manager (same-ticker decisions + cross-ticker lessons), written by the Memory Log step"]
    memory_note: Annotated[str, "What the Memory Log step could not settle or read this run, for the report; empty when all went well"]
    portfolio_context: Annotated[str, "Caller-supplied holdings and cash, rendered at run start; empty when not provided"]

    # --- Point-in-time input provenance (INV-03) -----------------------------
    # Per-input real data cutoffs from the analysts that actually received the
    # data, merged with a pure reducer (idempotent, order-independent, keeps all
    # distinct fact versions). D's guard reads this; C never decides REVIEW here.
    input_provenance: Annotated[list[InputProvenance], _merge_input_provenance]
