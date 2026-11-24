"""INV-02: the decision's suggested position size must be a percentage <= the cap.

The size this guards is the Portfolio Manager's own, as recorded in its
``Executive Summary``: the schema tells the model that field is "a concise action
plan covering entry strategy, position sizing, key risk levels, and time
horizon" (see ``agents.schemas.PortfolioDecision.executive_summary``), so that is
where the decision states how much the caller should hold. The Executive Summary
is the only sizing that belongs to the final decision; the Trader's
``position_sizing`` is an input to it and is deliberately not read here.

Scope: extraction is confined to the Executive Summary span and does not fall
back to the rest of the decision text. A percentage quoted in the investment
thesis, or in a Trader excerpt the summary repeats, is not the decision's own
size and must not be attributed to it.

This module imports only the standard library plus the INV-01 rating guard it
composes with, and calls no model.

Limitation, stated plainly: the Executive Summary is prose, not a typed field, so
a decision that states its intent without a percentage ("small starter", "build
on confirmation") resolves to REVIEW. That is what INV-02 requires of an
unparseable size, but it means the guard's practical effect is "no number stated,
no trade" and REVIEW will be a common outcome, not an exceptional one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tradingagents.safety.guard import (
    RATING_REVIEW,
    GuardVerdict,
    check_rating,
)

# The configured maximum exposure, as a percentage of total portfolio value.
# INV-02's cap. A size exactly at the cap passes; anything above it does not.
MAX_POSITION_PCT = 10.0

SIZING_RULE_VERSION = "inv02-v1"

# Reasons are stable identifiers, not prose, so a log or a test can match them.
PASS = "within_cap"
VETO_OVER_CAP = "over_cap"
VETO_AMBIGUOUS = "ambiguous_sizing"
VETO_UNPARSEABLE = "unparseable_sizing"
VETO_NO_SIZE = "no_position_size"
VETO_NO_SUMMARY = "missing_executive_summary"
VETO_NOT_TEXT = "not_text"

# Per-sentence splitting: a size is stated in a sentence of its own, and two
# sentences may each carry one. Terminal punctuation, or a newline. A full stop
# between two digits is a decimal point, not a sentence end ("6.5% of ...").
_SENTENCE_RE = re.compile(r"(?<!\d)[.!?;](?:\s+|$)|\n+")

# The Executive Summary label, as ``render_pm_decision`` emits it, and as a
# free-text reply may write it (markdown emphasis optional).
_SUMMARY_LABEL_RE = re.compile(
    r"(?im)^[ \t>*_#-]*executive[ \t]+summary[ \t]*[*_]*[ \t]*:[ \t]*"
)

# The next section header ends the summary: "**Investment Thesis**:", etc.
_NEXT_HEADER_RE = re.compile(r"(?m)^[ \t]*(?:[*_#]{1,3}[ \t]*)?[A-Z][\w /-]{1,40}[ \t]*[*_]*[ \t]*:")

# One percentage: digits, optional decimal, then the sign. Matched word-bounded
# so "15x" or "1.5" without a percent sign are not read as percentages.
#
# Two numbers joined by range punctuation ("5%-8%", "5–8%", "5 to 8%") are one
# written range, not two stated sizes. _PERCENT_RE consumes a range-shaped pair,
# including the shorthand where only the last number carries the sign, so the
# range can never be silently narrowed to its upper endpoint.
_RANGE_JOIN = r"[ \t]*%?[ \t]*(?:-|–|—|to\b|through\b)[ \t]*"
_NUM = r"\d+(?:\.\d+)?"
_PERCENT_RE = re.compile(rf"(?<![\w.]){_NUM}(?:{_RANGE_JOIN}{_NUM})?[ \t]*%")
_PERCENT_RANGE_RE = re.compile(
    rf"(?<![\w.]){_NUM}(?:{_RANGE_JOIN}{_NUM})[ \t]*%", re.IGNORECASE
)

# The position words a sizing sentence is recognised by.
_POSITION_WORD = (
    r"(?:position|positioning|sizing|sized|portfolio|allocation|allocate|allocated"
    r"|exposure|exposed|stake|book|weight|weighting)"
)
# A percentage is read as a size only in a sentence that also says what it sizes...
_POSITION_CONTEXT_RE = re.compile(rf"\b{_POSITION_WORD}\b", re.IGNORECASE)
# ...or directly beside a position word ("6% portfolio cap", "5% of the book").
_PERCENT_POSITION_RE = re.compile(
    rf"%[ \t]*(?:of[ \t]+(?:the[ \t]+|our[ \t]+|total[ \t]+|current[ \t]+)?)?"
    rf"(?:\w+[ \t]+){{0,2}}?{_POSITION_WORD}\b",
    re.IGNORECASE,
)
# A percentage qualified as a target, stop or threshold describes the trade's
# outcome or risk control, not its size, even when the sentence names a position.
_NON_SIZE_QUALIFIER_RE = re.compile(
    r"\b(?:upside|downside|target|targets|stop|stops|stop-loss|stop[ \t]+loss"
    r"|gain|gains|loss|losses|return|returns|yield|yields|drawdown|payoff|proceeds"
    r"|move|moves|growth|margin|margins)\b",
    re.IGNORECASE,
)

# A deferral word ("or", "another", "on confirmation") marks a split: the
# summary states more than one total, even if only one carries a percentage.
# "Add another 8% on the breakout" names no position word, so the
# position-context rule alone would let "5% of the portfolio" stand — but the
# sentence has said 5% is not the whole size, and which total is meant is not
# decidable by rule.
#
# Deliberately narrow: a plain "and" is not deferral, because "6% of the
# portfolio and add on confirmation" names one size. "then" is not deferral
# either, because it chains clauses ("Enter 5%, then stop at 3%") whose
# percentages are read separately.
_DEFERRAL_RE = re.compile(
    r"\b(?:later|next|another|afterwards?|subsequently|or"
    r"|on[ \t]+(?:a[ \t]+)?(?:confirmation|strength|breakout|dip|pullback|retest))\b",
    re.IGNORECASE,
)

# Words that begin the size half of a sentence, versus words that close it.
# "Enter 5% of the portfolio, then exit if it falls 3%" states one size and one
# exit; "Buy 5% of the portfolio, scaling to 12%" states two sizes.
_SIZE_COMMITMENT_RE = re.compile(
    r"\b(?:enter|buy|buying|open|add|adding|scale|scaling|size|sizing|initiate"
    r"|build|building|allocate|take|hold|maintain|use|start|begin|establish)\b",
    re.IGNORECASE,
)
_EXIT_WORD_RE = re.compile(
    r"\b(?:exit|exits|exiting|stop|stops|stop-loss|trim|trims|trimming"
    r"|take[ \t]+profit|target|targets|cut|reduce|halve)\b",
    re.IGNORECASE,
)
# A comma at the start of an exit clause joins two clauses ("..., then exit").
# A comma with no following conjunction ("5% of the portfolio, stop at 3%")
# merely separates the size's own clauses, so the exit does not cut there.
_NEXT_CLAUSE_RE = re.compile(r",[ \t]*(?:and[ \t]+then|then|and|or)\b", re.IGNORECASE)

# Expressions that name a size without giving a percentage of the portfolio.
# They are rejected explicitly so the reason says why, rather than falling into
# a generic parse failure.
_DASH = r"[-\u2010\u2011]"
_UNSUPPORTED_PATTERNS = (
    (re.compile(rf"\ball[ \t]*{_DASH}?[ \t]*in\b", re.IGNORECASE), "all_in"),
    (re.compile(r"(?<![\w.])" + _NUM + r"[ \t]*x\b", re.IGNORECASE), "leverage_multiple"),
    (re.compile(r"\bleverag\w*\b|\blever\w*\b", re.IGNORECASE), "leverage"),
    # A ratio ("1:2 risk-reward") or a bare fraction ("1/2 of the book").
    (re.compile(r"(?<![\w.])" + _NUM + r"[ \t]*:[ \t]*\d+", re.IGNORECASE), "ratio"),
    (re.compile(r"(?<![\w.])\d+[ \t]*/[ \t]*\d+", re.IGNORECASE), "fraction"),
)


@dataclass(frozen=True)
class SizingVerdict:
    """The sizing gate's decision.

    ``percent`` is the parsed size only when the size passed; it is ``None`` for
    every veto, so a caller cannot read a number out of a rejected decision.
    """

    passed: bool
    percent: float | None
    reason: str
    detail: str = ""
    rule_version: str = SIZING_RULE_VERSION


def _not_text(value: object) -> SizingVerdict:
    return SizingVerdict(False, None, VETO_NOT_TEXT, f"not text: {type(value).__name__}")


def executive_summary(decision_text: object) -> str | None:
    """The Executive Summary span of a decision, or ``None`` if there is none.

    Reads from the ``Executive Summary`` label to the next section header. The
    summary is where the decision states whether it opened, held or closed a
    position and how much; nothing outside it is the decision's size.

    ``None`` (no summary at all) is distinct from ``""`` (an empty one), but both
    are a missing size to the gate.
    """
    if not isinstance(decision_text, str):
        return None
    label = _SUMMARY_LABEL_RE.search(decision_text)
    if label is None:
        return None
    body = label.end()
    rest = decision_text[body:]
    header = _NEXT_HEADER_RE.search(rest)
    span = rest[: header.start()] if header else rest
    return span.strip()


def _sentences(span: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(span) if s.strip()]


def _size_clause(sentence: str) -> str:
    """``sentence`` up to the exit clause, if it has one.

    "Enter 5% of the portfolio, then exit if it falls 3%" states a size and an
    exit; the exit percentages size the loss, not the position. Everything from
    the first exit word after the position's percentage is cut, so a one-size
    sentence is not read as two conflicting sizes.
    """
    percent = _PERCENT_RE.search(sentence)
    if percent is None or _SIZE_COMMITMENT_RE.search(sentence) is None:
        return sentence
    exit_ = _EXIT_WORD_RE.search(sentence[percent.end():])
    if exit_ is None:
        return sentence
    # "..., then exit if it falls 3%": a comma before an exit verb separates
    # clauses. A comma right after the percentage ("5% of the portfolio, stop at
    # 3%") does not, so only ", then"/", and then"/", exit"-style joins are cut.
    tail = sentence[percent.end(): percent.end() + exit_.start()]
    if "," in tail and not _NEXT_CLAUSE_RE.search(tail):
        return sentence
    return sentence[: percent.end() + exit_.start()]


def _size_clause_is_whole(sentence: str) -> bool:
    """Whether the size clause before any exit clause is a single clear size."""
    clause = _size_clause(sentence)
    if _PERCENT_RANGE_RE.search(clause):
        return False
    return _single_percent(clause) is not None


def _single_percent(sentence: str) -> float | None:
    """The one percentage of the position a sentence states, or None.

    A range ("5%-8%") is consumed as a single whole-range match, which is not a
    single size, so it is left to the caller's ambiguity branch rather than
    silently narrowed to an endpoint. Exit clauses are cut first (see
    ``_size_clause``).
    """
    values = [
        float(m.group(0).rstrip().rstrip("%").strip())
        for m in _PERCENT_RE.finditer(_size_clause(sentence))
    ]
    return values[0] if len(values) == 1 else None


def _percent_sentences(span: str) -> tuple[list[str], bool]:
    """Sentences that state a position size, and whether that reading was exact.

    A summary is prose about the trade, and percentages in it also describe
    things that are not the position: an upside target ("+15%"), a stop distance
    ("3% stop"), a threshold ("6% payout"). Reading any of those as the size
    would make a size-less decision look over-cap or ambiguous.

    A percentage counts as a size only where it sits beside a position word
    ("5% of the portfolio", "6% portfolio cap") in a sentence that does not
    describe a different total. When a sentence names a position but also
    carries a trade's outcome ("3% stop") or a second, deferred total ("add
    another 8%"), it is still a size sentence, but which percentage is the size
    is not decidable by rule; the second return value says so, and the caller
    resolves that to REVIEW rather than picking one.
    """
    sized: list[str] = []
    deferral = False
    for sentence in _sentences(span):
        if not _PERCENT_RE.search(sentence):
            # A deferred total with no percentage of its own still splits the
            # size: "$5k now, add later" is not a size the guard can read.
            if _DEFERRAL_RE.search(sentence) and _POSITION_CONTEXT_RE.search(sentence):
                deferral = True
            continue
        mentions_position = _POSITION_CONTEXT_RE.search(sentence) is not None
        if _DEFERRAL_RE.search(sentence):
            # Deferral only means "a second, different total" when it is not the
            # size clause's own exit: "Enter 5% of the portfolio, then exit if it
            # falls 3%" states one size. Otherwise it is a split — "Add another
            # 8% on the breakout", "scaling to 12% on strength".
            if not (
                mentions_position
                and _SIZE_COMMITMENT_RE.search(sentence)
                and _size_clause_is_whole(sentence)
            ):
                deferral = True
                continue
        if not mentions_position:
            continue
        if _PERCENT_POSITION_RE.search(sentence):
            sized.append(sentence)
            continue
        if _NON_SIZE_QUALIFIER_RE.search(sentence):
            # A position percentage qualified by a trade outcome, with no
            # deferred total ("6% of portfolio — 3% stop"): which one sizes the
            # position is not decidable by rule.
            return [], True
        sized.append(sentence)
    if deferral:
        return [], True
    return sized, False


def check_position_size(decision_text: object) -> SizingVerdict:
    """Decide whether the decision's Executive Summary states a valid size.

    Passes only a single percentage of the portfolio that is above zero and at or
    below ``MAX_POSITION_PCT``. Everything else resolves to REVIEW.
    """
    if not isinstance(decision_text, str):
        return _not_text(decision_text)

    summary = executive_summary(decision_text)
    if summary is None:
        return SizingVerdict(False, None, VETO_NO_SUMMARY, "no Executive Summary section")
    if not summary:
        return SizingVerdict(False, None, VETO_NO_SIZE, "Executive Summary is empty")

    for pattern, name in _UNSUPPORTED_PATTERNS:
        match = pattern.search(summary)
        if match:
            return SizingVerdict(
                False, None, VETO_UNPARSEABLE, f"{name}: {match.group(0)!r}"
            )

    sized: list[tuple[str, float]] = []
    candidates, ambiguous = _percent_sentences(summary)
    for sentence in candidates:
        if _PERCENT_RANGE_RE.search(sentence):
            return SizingVerdict(False, None, VETO_AMBIGUOUS, f"range: {sentence!r}")
        percent = _single_percent(sentence)
        if percent is None:
            # Several percentages of the position in one sentence: not one size.
            return SizingVerdict(False, None, VETO_AMBIGUOUS, f"several sizes: {sentence!r}")
        sized.append((sentence, percent))

    if not sized:
        if ambiguous:
            return SizingVerdict(
                False, None, VETO_AMBIGUOUS, "a percentage names a position but not a size"
            )
        return SizingVerdict(False, None, VETO_NO_SIZE, "no position size stated")

    # Two different percentages anywhere in the summary are conflicting advice,
    # even when each sits in its own sentence.
    distinct = {p for _, p in sized}
    if len(distinct) > 1:
        return SizingVerdict(False, None, VETO_AMBIGUOUS, f"conflicting sizes: {sorted(distinct)}")

    percent = sized[0][1]
    if percent <= 0:
        # "Hold nothing" is not a position, and a zero is not a size to endorse:
        # it would let an unusable decision leave the pipeline as a tradeable
        # rating carrying no exposure.
        return SizingVerdict(False, None, VETO_UNPARSEABLE, f"not a positive size: {percent:g}%")
    if percent > MAX_POSITION_PCT:
        return SizingVerdict(
            False, None, VETO_OVER_CAP, f"{percent:g}% > {MAX_POSITION_PCT:g}%"
        )
    return SizingVerdict(True, percent, PASS)


def apply_to_rating(rating: object, decision_text: object) -> GuardVerdict:
    """The composed INV-01 + INV-02 verdict for a decision.

    INV-01 runs first. A rating that already failed it stays REVIEW no matter
    how sound the size is: a valid size must not lift a veto. When the rating
    passes, the size decides — an invalid size forces REVIEW on an otherwise
    tradeable rating.

    The returned ``GuardVerdict.reason`` names the rule that produced the final
    verdict, so INV-01 and INV-02 vetoes stay distinguishable in a log.
    """
    rating_verdict = check_rating(rating)
    if not rating_verdict.tradeable:
        return rating_verdict

    sizing_verdict = check_position_size(decision_text)
    if sizing_verdict.passed:
        return GuardVerdict(
            passed=True,
            rating=rating_verdict.rating,
            reason=PASS,
            rule_version=SIZING_RULE_VERSION,
        )
    return GuardVerdict(
        passed=False,
        rating=RATING_REVIEW,
        reason=sizing_verdict.reason,
        rule_version=SIZING_RULE_VERSION,
    )
