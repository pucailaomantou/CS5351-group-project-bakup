"""One deterministic gate over INV-01, INV-02 and INV-03.

The three invariants are implemented as independent, model-free checks:

- ``guard.check_rating``      — INV-01, the rating may be traded (``"REVIEW"`` never may)
- ``sizing.check_position_size`` — INV-02, the size is a stated percentage within the cap
- ``freshness.check_freshness``  — INV-03, every required PIT input is dated and fresh

Nothing in the pipeline calls them yet. This module is the one place that does:
it invokes all three on a finished run's state, aggregates their verdicts, and
returns a single decision a caller can act on. It is deliberately independent of
LangGraph — ``evaluate_guard`` takes a mapping and returns a frozen result — so
it can be wrapped as a node later without being tied to the graph now.

The aggregation rule is a plain conjunction, and a veto is final::

    guard_passed = inv01.passed and inv02.passed and inv03.passedgit status

A passing check can never lift another check's veto, and the approved rating is
either the rating INV-01 published or ``REVIEW`` — never a tier that one of the
checks rejected.

What this module does not do: it does not re-implement any rule. The cap, the
rating enum, the freshness thresholds and reason codes all live in their own
modules and are read here, not duplicated. It also does not write the result
back into the state — deciding whether a rejected run still publishes a rating
is a graph-level question for the team to settle.

Execution errors are distinguished from validation failures. If a check raises
rather than returning a verdict, the run fails closed, the remaining checks still
run, and the check's entry is marked ``execution_error`` with the exception type
and message. That keeps a crash from being mistaken for a pass, or for a
deliberate veto.

This module imports only the standard library and the three checks, and calls no
model.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass

from tradingagents.safety.freshness import FreshnessVerdict, check_freshness
from tradingagents.safety.guard import RATING_REVIEW, GuardVerdict, check_rating
from tradingagents.safety.sizing import SizingVerdict, check_position_size

# The check names, matching each module's own ``CHECK_NAME`` where it has one.
# INV-01 and INV-02 do not carry a ``check_name`` field, so the aggregate names
# them here rather than inventing one inside their modules.
CHECK_INV01 = "INV-01"
CHECK_INV02 = "INV-02"
CHECK_INV03 = "INV-03"

# How an entry came to fail. ``validation_failure`` is a check that ran and
# vetoed; ``execution_error`` is a check that raised before it could decide.
OUTCOME_PASS = "pass"
OUTCOME_VALIDATION_FAILURE = "validation_failure"
OUTCOME_EXECUTION_ERROR = "execution_error"

# The reason recorded for a check that raised. It is not one of the checks' own
# reason codes, so a log that greps for a module's reasons never sees it.
REASON_EXECUTION_ERROR = "execution_error"

# The aggregate's own rule identity, for GOV-01 provenance. "v1" describes the
# conjunction below; bump it only when that rule changes meaning.
AGGREGATE_RULE_VERSION = "agg-v1"

# The state keys the gate reads. They are the Portfolio Manager's own outputs
# plus the run's analysis date, as ``AgentState`` declares them.
_KEY_RATING = "final_rating"
_KEY_DECISION = "final_trade_decision"
_KEY_TRADE_DATE = "trade_date"
_KEY_PROVENANCE = "input_provenance"

# The checks the gate runs, in the order they appear in the output. Fixed order
# so a serialised result is byte-identical run to run.
CHECK_ORDER = (CHECK_INV01, CHECK_INV02, CHECK_INV03)


@dataclass(frozen=True)
class DeterministicGuardResult:
    """The gate's decision over a whole run.

    ``passed`` is the conjunction of the three checks and the single thing a
    caller may act on. ``final_rating`` is the rating to publish: INV-01's
    normalised rating when everything passed, ``"REVIEW"`` otherwise, so a veto
    is never reported as a tradeable tier. ``checks`` maps each check name to its
    entry, and ``as_dict()`` serialises the whole result.

    ``checks`` is immutable in practice: it is a mapping of plain dicts, and the
    dicts are rebuilt on every run, so mutating one cannot reach back into a
    verdict the checks returned.
    """

    passed: bool
    final_rating: str
    checks: Mapping[str, dict]
    rule_version: str = AGGREGATE_RULE_VERSION

    def as_dict(self) -> dict:
        """The result as a JSON-safe dict, keys in a fixed order.

        ``checks`` is **deep**-copied from the entries: a caller may mutate any
        part of what it is given — an INV-01 ``details`` field, INV-03's
        ``failures`` list — without changing this result or what a later
        ``as_dict()`` returns. A deep copy is used rather than a per-entry
        ``dict(...)`` because the entries nest dicts and lists, and a shallow
        copy shares those.

        The values are already JSON-safe (the entries are built from strings,
        bools, numbers, ``None`` and plain dicts/lists), so the copy is a copy,
        not a conversion.
        """
        return {
            "passed": self.passed,
            "final_rating": self.final_rating,
            "rule_version": self.rule_version,
            "checks": {name: copy.deepcopy(self.checks[name])
                       for name in CHECK_ORDER if name in self.checks},
        }


def _entry(
    check_name: str,
    verdict_passed: bool,
    reason: str,
    rule_version: str,
    details: dict,
    outcome: str,
) -> dict:
    """One check's envelope, the shape shared by every entry in ``checks``."""
    return {
        "passed": verdict_passed,
        "check_name": check_name,
        "reason": reason,
        "rule_version": rule_version,
        "outcome": outcome,
        "details": details,
    }


def _error_entry(check_name: str, exc: BaseException) -> dict:
    """A check that raised, recorded the same way a veto is.

    ``passed`` is False so the conjunction fails even if the other two passed,
    and the exception's type and message are kept as evidence. The message is a
    string, so the entry stays JSON-serialisable.
    """
    return _entry(
        check_name,
        False,
        REASON_EXECUTION_ERROR,
        "",
        {"error_type": type(exc).__name__, "error_message": str(exc)},
        OUTCOME_EXECUTION_ERROR,
    )


def _guard_entry(verdict: GuardVerdict) -> dict:
    """INV-01's verdict in the common envelope.

    ``rating`` is kept verbatim: it is the value the check says to publish, so
    ``"REVIEW"`` on a veto is evidence, not a hole.
    """
    return _entry(
        CHECK_INV01,
        verdict.passed,
        verdict.reason,
        verdict.rule_version,
        {"rating": verdict.rating},
        OUTCOME_PASS if verdict.passed else OUTCOME_VALIDATION_FAILURE,
    )


def _sizing_entry(verdict: SizingVerdict) -> dict:
    """INV-02's verdict in the common envelope.

    ``percent`` is ``None`` on a veto and ``detail`` says why, both verbatim.
    """
    return _entry(
        CHECK_INV02,
        verdict.passed,
        verdict.reason,
        verdict.rule_version,
        {"percent": verdict.percent, "detail": verdict.detail},
        OUTCOME_PASS if verdict.passed else OUTCOME_VALIDATION_FAILURE,
    )


def _freshness_entry(verdict: FreshnessVerdict) -> dict:
    """INV-03's verdict in the common envelope.

    ``verdict.details`` is a tuple of plain dicts; it becomes a list of fresh
    copies so the serialised form is JSON-safe and cannot alias the verdict.
    Every per-input field (analyst, tool, call_id, as_of, semantics, thresholds,
    ages, reason, message) is carried through untouched.
    """
    return _entry(
        CHECK_INV03,
        verdict.passed,
        verdict.reason,
        verdict.rule_version,
        {"failures": [dict(failure) for failure in verdict.details]},
        OUTCOME_PASS if verdict.passed else OUTCOME_VALIDATION_FAILURE,
    )


def evaluate_guard(state: object) -> DeterministicGuardResult:
    """Run all three checks over a finished run's state and aggregate them.

    Reads, and only reads, the four keys ``AgentState`` already declares:

    - ``final_rating`` — the rating to judge (INV-01)
    - ``final_trade_decision`` — the rendered decision whose Executive Summary
      states the size (INV-02)
    - ``trade_date`` and ``input_provenance`` — the reference date and PIT
      records (INV-03)

    A state that is not a mapping, or that lacks a key, fails closed through the
    checks themselves: a missing rating is ``missing_or_empty``, a missing
    decision is ``not_text``, and a missing date or provenance is the freshness
    check's own run-level reason. Nothing is defaulted here to make a run pass.

    A mapping whose ``.get`` itself raises is treated as unreadable: rather than
    letting that exception escape the gate, extraction is guarded and the three
    checks are recorded as ``execution_error`` entries, so the result is still a
    fail-closed REVIEW with the extraction failure named in the audit. An
    exception from a single check is recorded the same way, and the other checks
    still run, so one failure does not hide the rest of the audit.
    """
    if isinstance(state, Mapping):
        try:
            rating = state.get(_KEY_RATING)
            decision = state.get(_KEY_DECISION)
            provenance = state.get(_KEY_PROVENANCE)
            trade_date = state.get(_KEY_TRADE_DATE)
        except Exception as exc:  # noqa: BLE001 — a broken mapping must not crash the gate
            # Which key raised is unknown, so every extracted value is treated as
            # absent and the state is not handed to the freshness check at all.
            # All three checks are then recorded as execution errors: the gate
            # could not read the run, which is not a verdict about the input.
            rating = decision = provenance = trade_date = None
            state = None
            extraction_error = exc
        else:
            extraction_error = None
    else:
        rating = decision = provenance = trade_date = None
        state = None
        extraction_error = None

    checks: dict[str, dict] = {}

    if extraction_error is not None:
        # The state could not be read at all, so no check can judge real data.
        # Recording all three as execution errors is what "extraction failed"
        # means for the audit: it is not a verdict about the market, it is a
        # failure of this layer to see the run.
        for check_name in CHECK_ORDER:
            checks[check_name] = _error_entry(check_name, extraction_error)
        return DeterministicGuardResult(passed=False, final_rating=RATING_REVIEW, checks=checks)

    try:
        verdict = check_rating(rating)
    except Exception as exc:  # noqa: BLE001 — a check must not crash the gate
        checks[CHECK_INV01] = _error_entry(CHECK_INV01, exc)
    else:
        checks[CHECK_INV01] = _guard_entry(verdict)

    try:
        verdict = check_position_size(decision)
    except Exception as exc:  # noqa: BLE001
        checks[CHECK_INV02] = _error_entry(CHECK_INV02, exc)
    else:
        checks[CHECK_INV02] = _sizing_entry(verdict)

    try:
        verdict = check_freshness(
            state if isinstance(state, Mapping) else {"input_provenance": None,
                                                      "trade_date": None}
        )
    except Exception as exc:  # noqa: BLE001
        checks[CHECK_INV03] = _error_entry(CHECK_INV03, exc)
    else:
        checks[CHECK_INV03] = _freshness_entry(verdict)

    passed = all(checks[name]["passed"] for name in CHECK_ORDER)

    if passed:
        # INV-01 published the rating unchanged when it passed; read it back
        # from its own entry rather than from a local, so nothing outside the
        # collected evidence decides what is published.
        final_rating = checks[CHECK_INV01]["details"]["rating"]
    else:
        final_rating = RATING_REVIEW

    return DeterministicGuardResult(passed=passed, final_rating=final_rating, checks=checks)
