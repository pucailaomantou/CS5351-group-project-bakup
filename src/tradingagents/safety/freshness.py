"""INV-03: a key PIT input must be dated, reliable, and fresh on the trade date.

INV-03 is a decision-layer invariant. ``dataflows.date_window.as_of`` clamps a
requested date to the trade date, so no tool reaches the future, but nothing
rejects an input that is *old*: a run dated today can be handed a market row
from last week, a headline from last month, or a balance sheet whose fiscal
period ended six months ago. This module decides, from ``AgentState`` alone,
whether every required input that reached an analyst is fresh enough to decide
on.

What it checks, and nothing else:

- Each record's structure and types, without repairing a malformed one.
- The required input classes are present, ``available``, ``time_reliable`` and
  carry a semantic the class supports.
- A parsed ``as_of`` not later than ``trade_date``, whose age in calendar days
  is at or below the threshold for that (input class, semantic) pair.
- Every record: a fresh record never masks a stale one recorded beside it.

The size of a *window* (how many days a news lookback spans) is an existing
concern of ``date_window`` and is out of scope here; this module judges one
dated input at a time.

The module imports only the standard library and calls no model, so the verdict
is deterministic and can be replayed from a record.

The public entry point is ``check_freshness(state)``; ``evaluate`` is the same
check over explicit arguments for a caller that already has them. The result is
a ``FreshnessVerdict``: a pass/fail, a stable reason, and one detail dict per
input that failed, each naming its analyst, tool and call id so a reader can
find the exact input that was too old.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------------------
# Rule identity (GOV-01)
# ---------------------------------------------------------------------------

# Bump the version only when the rule below changes meaning, so a decision
# record can say which INV-03 rule judged its inputs.
FRESHNESS_RULE_VERSION = "inv03-v1"

CHECK_NAME = "INV-03"

# The unit every threshold is expressed in. Kept as one constant so a later
# move to, say, trading days is a single edit rather than a search.
THRESHOLD_UNIT = "calendar_days"

# ---------------------------------------------------------------------------
# The provenance vocabulary
# ---------------------------------------------------------------------------
#
# The enum *values* are the strings teammate C's records carry. They are named
# here, once, so a rename in the producer is one edit here and not a search
# through the checks.

# Input classes.
MARKET = "market"
SENTIMENT = "sentiment"
NEWS = "news"
FUNDAMENTALS = "fundamentals"

# Temporal semantics: what ``as_of`` means for the record's data.
MARKET_OBSERVATION_DATE = "market_observation_date"
SENTIMENT_OBSERVATION_DATE = "sentiment_observation_date"
NEWS_PUBLICATION_DATE = "news_publication_date"
# A fundamentals figure carries the date the company filed it: an actual
# disclosure date.
FUNDAMENTALS_DISCLOSURE_DATE = "fundamentals_disclosure_date"
# No disclosure date was available, so ``as_of`` is the fiscal period's end.
# That is a conservative lower bound on when the figure became public (a
# company files weeks after the period ends), not a publication timestamp, so
# it must never be judged by the disclosure-date threshold.
FUNDAMENTALS_FISCAL_PERIOD_END = "fundamentals_fiscal_period_end"

# Supported semantics per input class. A record whose semantics is not listed
# for its class is unsupported and fails closed.
SEMANTICS_BY_CLASS: dict[str, tuple[str, ...]] = {
    MARKET: (MARKET_OBSERVATION_DATE,),
    SENTIMENT: (SENTIMENT_OBSERVATION_DATE,),
    NEWS: (NEWS_PUBLICATION_DATE,),
    FUNDAMENTALS: (FUNDAMENTALS_DISCLOSURE_DATE, FUNDAMENTALS_FISCAL_PERIOD_END),
}

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
#
# All provisional engineering defaults agreed for the first implementation, in
# calendar days: the maximum age an input may have and still be decided on. A
# threshold is (input class, semantic), so fundamentals' two temporal
# references are judged separately rather than as one number.
#
# Not claims about universally correct data policy. Change them here, and in
# one place only, after the team agrees the number and the unit.
DEFAULT_THRESHOLDS_DAYS: dict[tuple[str, str], int] = {
    (MARKET, MARKET_OBSERVATION_DATE): 3,
    (SENTIMENT, SENTIMENT_OBSERVATION_DATE): 3,
    (NEWS, NEWS_PUBLICATION_DATE): 2,
    (FUNDAMENTALS, FUNDAMENTALS_DISCLOSURE_DATE): 120,
    (FUNDAMENTALS, FUNDAMENTALS_FISCAL_PERIOD_END): 180,
}

# The input classes that must be present for a decision to be trustable.
#
# INV-03's statement covers "any key input"; it does not name the classes. The
# default mirrors the pipeline's own analyst set (the four sources in
# ``graph/analyst_execution.py``); a caller that ran fewer analysts passes its
# own tuple. Keep this in step with the analyst selection when INV-03 is wired
# into the graph.
REQUIRED_INPUT_CLASSES: tuple[str, ...] = (MARKET, SENTIMENT, NEWS, FUNDAMENTALS)


# ---------------------------------------------------------------------------
# Stable reason identifiers
# ---------------------------------------------------------------------------
#
# Record-level reasons, one per detail entry. They say what was wrong with *that
# input*.
MALFORMED_RECORD = "MALFORMED_RECORD"
MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
UNAVAILABLE = "UNAVAILABLE"
MISSING_AS_OF = "MISSING_AS_OF"
UNRELIABLE_TIME = "UNRELIABLE_TIME"
INVALID_DATE = "INVALID_DATE"
INVALID_PRECISION = "INVALID_PRECISION"
UNSUPPORTED_SEMANTIC = "UNSUPPORTED_SEMANTIC"
UNKNOWN_INPUT_CLASS = "UNKNOWN_INPUT_CLASS"
NO_THRESHOLD = "NO_THRESHOLD"
FUTURE_DATED = "FUTURE_DATED"
STALE_INPUT = "STALE_INPUT"

# Run-level reasons: the check could not judge the inputs at all.
MISSING_TRADE_DATE = "MISSING_TRADE_DATE"
INVALID_TRADE_DATE = "INVALID_TRADE_DATE"
MISSING_PROVENANCE = "MISSING_PROVENANCE"
INVALID_PROVENANCE = "INVALID_PROVENANCE"

PASS = "fresh"

# Accepted ``precision`` values. A date-only value keeps ``"date"`` and is
# compared at date level; a timestamp is compared at its own level. Nothing is
# widened from a date to a timestamp or the reverse.
PRECISION_DATE = "date"
PRECISION_DATETIME = "datetime"
SUPPORTED_PRECISIONS: tuple[str, ...] = (PRECISION_DATE, PRECISION_DATETIME)

# The fields every record must carry, with the type ``bool`` expected for the
# two flags. ``as_of`` and ``missing_reason`` are checked separately because
# they may legitimately be ``None``.
_TEXT_FIELDS = ("analyst", "tool", "call_id", "input_class", "precision", "semantics")
_FLAG_FIELDS = ("available", "time_reliable")


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FreshnessVerdict:
    """INV-03's decision on a run's PIT inputs.

    ``passed`` is the single thing a caller may act on. ``reason`` is ``"fresh"``
    on a pass and a stable identifier otherwise. ``details`` holds one entry per
    input that failed, each a plain dict so it serialises into a decision record
    without a converter; it is empty on a pass. ``rule_version`` records which
    rule judged the inputs (GOV-01).
    """

    passed: bool
    check_name: str = CHECK_NAME
    reason: str = PASS
    details: tuple[dict, ...] = ()
    rule_version: str = FRESHNESS_RULE_VERSION

    def as_dict(self) -> dict:
        """The verdict as a JSON-safe dict, the shape the illustrative output names."""
        return {
            "passed": self.passed,
            "check_name": self.check_name,
            "reason": self.reason,
            "details": list(self.details),
            "rule_version": self.rule_version,
        }


def _failure(detail: dict, rule_version: str = FRESHNESS_RULE_VERSION) -> FreshnessVerdict:
    """A failed verdict carrying a single detail entry."""
    return FreshnessVerdict(passed=False, reason=detail["reason"], details=(detail,), rule_version=rule_version)


def _detail(
    record: Mapping | None,
    reason: str,
    *,
    message: str,
    threshold_days: int | None = None,
    actual_age_days: int | None = None,
) -> dict:
    """One failure, tied back to the input that caused it.

    Fields come from the record where it has them, so an unreadable record still
    reports whichever identifying fields it did carry; ``None`` where it did not.
    """
    record = record if isinstance(record, Mapping) else {}

    def field_of(name):
        value = record.get(name)
        return value if isinstance(value, str) else None

    return {
        "analyst": field_of("analyst"),
        "tool": field_of("tool"),
        "call_id": field_of("call_id"),
        "input_class": field_of("input_class"),
        "as_of": field_of("as_of"),
        "semantics": field_of("semantics"),
        "threshold_days": threshold_days,
        "actual_age_days": actual_age_days,
        "reason": reason,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_date(value: object) -> date | None:
    """A ``YYYY-MM-DD`` date, or None.

    Strict, like ``dataflows.date_window._parse``: a loosely written date such as
    ``"2026-7-3"`` compares as text later than ``"2026-07-23"``, so it is refused
    rather than guessed at.

    The shape is checked as well as the calendar: ``strptime`` alone accepts
    zero padding too, so ``"2026-7-3"`` would parse as 3 July and be judged on a
    date nobody wrote. Only the canonical ``YYYY-MM-DD`` is a date here.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if f"{parsed:%Y-%m-%d}" == value else None


def _parse_as_of(value: object, precision: str) -> tuple[date | None, str | None]:
    """``(date, None)`` for a readable ``as_of``, else ``(None, reason)``.

    A ``date`` precision must parse as ``YYYY-MM-DD``. A ``datetime`` precision
    accepts an ISO 8601 timestamp as well, and a bare date (midnight), but is
    still reduced to a date for the age comparison: ages are whole calendar
    days, so the time of day never makes an input look fresher than it is.
    """
    if precision == PRECISION_DATE:
        parsed = _parse_date(value)
        return (parsed, None) if parsed is not None else (None, INVALID_DATE)
    if precision == PRECISION_DATETIME:
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).date(), None
            except ValueError:
                pass
        return None, INVALID_DATE
    # A precision this module does not understand: refuse rather than assume one.
    return None, INVALID_PRECISION


# ---------------------------------------------------------------------------
# Validation of one record
# ---------------------------------------------------------------------------

def _check_record(
    record: object,
    trade_day: date,
    thresholds: Mapping[tuple[str, str], int],
) -> dict | None:
    """The failure detail for one provenance record, or None if it is fresh.

    Fails closed at the first structural problem: a missing field, a wrong type,
    a flag that is not a real bool. Nothing is coerced, defaulted or repaired.
    """
    if not isinstance(record, Mapping):
        return _detail(None, MALFORMED_RECORD,
                       message=f"provenance record is {type(record).__name__}, not a mapping")

    for name in _TEXT_FIELDS:
        if name not in record:
            return _detail(record, MALFORMED_RECORD, message=f"record has no {name!r}")
        if not isinstance(record[name], str) or not record[name].strip():
            return _detail(record, MALFORMED_RECORD,
                           message=f"record field {name!r} is not a non-empty string")

    for name in _FLAG_FIELDS:
        if name not in record:
            return _detail(record, MALFORMED_RECORD, message=f"record has no {name!r}")
        if not isinstance(record[name], bool):
            # A truthy string ("false") or a 1 would silently pass as a flag.
            return _detail(record, MALFORMED_RECORD,
                           message=f"record field {name!r} is {type(record[name]).__name__}, not bool")

    if "as_of" not in record:
        return _detail(record, MALFORMED_RECORD, message="record has no 'as_of'")

    input_class = record["input_class"]
    semantics = record["semantics"]
    precision = record["precision"]

    supported = SEMANTICS_BY_CLASS.get(input_class)
    if supported is None:
        return _detail(record, UNKNOWN_INPUT_CLASS,
                       message=f"input class {input_class!r} is not a known PIT input class")
    if semantics not in supported:
        return _detail(record, UNSUPPORTED_SEMANTIC,
                       message=f"semantic {semantics!r} is not one of {list(supported)} for {input_class!r}")
    if precision not in SUPPORTED_PRECISIONS:
        return _detail(record, INVALID_PRECISION,
                       message=f"precision {precision!r} is not one of {list(SUPPORTED_PRECISIONS)}")

    threshold = thresholds.get((input_class, semantics))
    if threshold is None:
        # No threshold for a supported pair is a configuration gap, not a pass.
        return _detail(record, NO_THRESHOLD,
                       message=f"no freshness threshold configured for ({input_class!r}, {semantics!r})")

    # Availability and reliability are judged before the date: a record that
    # admits its time is unreliable has no trustworthy age to report.
    if not record["available"]:
        return _detail(record, UNAVAILABLE,
                       message=f"required input was not available"
                               + (f": {record['missing_reason']}" if isinstance(record.get("missing_reason"), str)
                                  and record["missing_reason"] else ""))
    if not record["time_reliable"]:
        return _detail(record, UNRELIABLE_TIME, threshold_days=threshold,
                       message="record states its temporal information is unreliable")
    if record["as_of"] is None:
        return _detail(record, MISSING_AS_OF, threshold_days=threshold,
                       message="record has no as-of date")

    as_of, parse_reason = _parse_as_of(record["as_of"], precision)
    if as_of is None:
        return _detail(record, parse_reason, threshold_days=threshold,
                       message=f"as-of {record['as_of']!r} is not a valid {precision}")

    # INV-03 forbids deciding on data from after the trade date; that is a
    # look-ahead, not merely staleness, so it is its own reason.
    if as_of > trade_day:
        return _detail(record, FUTURE_DATED, threshold_days=threshold,
                       actual_age_days=(as_of - trade_day).days,
                       message=f"as-of {as_of} is after the trade date {trade_day}")

    age = (trade_day - as_of).days
    if age > threshold:
        return _detail(record, STALE_INPUT, threshold_days=threshold, actual_age_days=age,
                       message=f"as-of {as_of} is {age} {THRESHOLD_UNIT} old; the limit is {threshold}")
    return None


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def evaluate(
    input_provenance: object,
    trade_date: object,
    *,
    required_classes: tuple[str, ...] = REQUIRED_INPUT_CLASSES,
    thresholds: Mapping[tuple[str, str], int] | None = None,
) -> FreshnessVerdict:
    """INV-03 over explicit arguments.

    ``input_provenance`` is the list of records; ``trade_date`` is the run's
    ``YYYY-MM-DD`` analysis date and the reference every age is measured from.
    ``required_classes`` defaults to the pipeline's four analyst inputs;
    ``thresholds`` defaults to ``DEFAULT_THRESHOLDS_DAYS``.

    Every failure is collected: all records are judged, and every required class
    that has no record at all adds its own entry. The verdict passes only when
    no entry was produced.
    """
    trade_day = _parse_date(trade_date)
    if trade_day is None:
        # Without a reference date no age is computable, so every input is
        # unjudgeable. The run-level reason says which problem it was.
        reason = MISSING_TRADE_DATE if trade_date in (None, "") else INVALID_TRADE_DATE
        return _failure({"reason": reason, "message": f"trade_date {trade_date!r} is not a YYYY-MM-DD date"})

    if input_provenance is None:
        return _failure({"reason": MISSING_PROVENANCE,
                         "message": "AgentState carries no input_provenance"})
    if not isinstance(input_provenance, (list, tuple)):
        return _failure({"reason": INVALID_PROVENANCE,
                         "message": f"input_provenance is {type(input_provenance).__name__}, not a list"})

    thresholds = DEFAULT_THRESHOLDS_DAYS if thresholds is None else thresholds
    details: list[dict] = []

    present_classes = set()
    for record in input_provenance:
        # Count a class as present only when a structurally valid record claims
        # it: a malformed record that cannot be read is not evidence the input came.
        if isinstance(record, Mapping):
            claimed = record.get("input_class")
            if isinstance(claimed, str) and all(
                isinstance(record.get(name), str) and record.get(name) for name in _TEXT_FIELDS
            ):
                present_classes.add(claimed)
        failure = _check_record(record, trade_day, thresholds)
        if failure is not None:
            details.append(failure)

    for input_class in required_classes:
        if input_class not in present_classes:
            details.append({
                "analyst": None, "tool": None, "call_id": None,
                "input_class": input_class, "as_of": None, "semantics": None,
                "threshold_days": None, "actual_age_days": None,
                "reason": MISSING_REQUIRED_INPUT,
                "message": f"required input class {input_class!r} has no provenance record",
            })

    if not details:
        return FreshnessVerdict(passed=True)
    return FreshnessVerdict(passed=False, reason=details[0]["reason"], details=tuple(details))


def check_freshness(
    state: object,
    *,
    required_classes: tuple[str, ...] = REQUIRED_INPUT_CLASSES,
    thresholds: Mapping[tuple[str, str], int] | None = None,
) -> FreshnessVerdict:
    """INV-03 over an ``AgentState`` mapping.

    Reads ``state["input_provenance"]`` and ``state["trade_date"]`` and changes
    nothing: no field is written back, so the Portfolio Manager's outputs are
    untouched. A state that is not a mapping, or lacks either key, fails closed.
    """
    if not isinstance(state, Mapping):
        return _failure({"reason": INVALID_PROVENANCE,
                         "message": f"state is {type(state).__name__}, not a mapping"})
    return evaluate(
        state.get("input_provenance"),
        state.get("trade_date"),
        required_classes=required_classes,
        thresholds=thresholds,
    )
