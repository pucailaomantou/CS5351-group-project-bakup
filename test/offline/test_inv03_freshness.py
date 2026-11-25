"""INV-03: required PIT inputs must be dated, reliable, and fresh on the trade date.

Every case builds a provenance list by hand and a fixed trade date, so nothing
here reads a vendor, a clock or a model. The cases judge the returned verdict,
not just a truthiness: the detail entry that identifies the failing input is
asserted too, because a gate that fails for the wrong reason is as wrong as one
that passes.

The check is judged on its own, as ``check_freshness(state)`` and
``evaluate(...)``. It is not wired into the graph yet, so a run that never calls
it cannot pass INV-03; that wiring is deliberately out of this file's scope.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tradingagents.safety.freshness import (
    CHECK_NAME,
    DEFAULT_THRESHOLDS_DAYS,
    FRESHNESS_RULE_VERSION,
    FUTURE_DATED,
    FUNDAMENTALS,
    FUNDAMENTALS_DISCLOSURE_DATE,
    FUNDAMENTALS_FISCAL_PERIOD_END,
    INVALID_DATE,
    INVALID_PROVENANCE,
    MALFORMED_RECORD,
    MARKET,
    MARKET_OBSERVATION_DATE,
    MISSING_AS_OF,
    MISSING_PROVENANCE,
    MISSING_REQUIRED_INPUT,
    NEWS,
    NEWS_PUBLICATION_DATE,
    NO_THRESHOLD,
    REQUIRED_INPUT_CLASSES,
    SENTIMENT,
    SENTIMENT_OBSERVATION_DATE,
    STALE_INPUT,
    THRESHOLD_UNIT,
    UNAVAILABLE,
    UNKNOWN_INPUT_CLASS,
    UNRELIABLE_TIME,
    UNSUPPORTED_SEMANTIC,
    check_freshness,
    evaluate,
)

FRESHNESS_MODULE = (
    Path(__file__).resolve().parents[2] / "src" / "tradingagents" / "safety" / "freshness.py"
)

TRADE_DATE = "2026-11-23"

# Semantics per input class, so a record builder cannot quietly pair the wrong two.
_SEMANTICS = {
    MARKET: MARKET_OBSERVATION_DATE,
    SENTIMENT: SENTIMENT_OBSERVATION_DATE,
    NEWS: NEWS_PUBLICATION_DATE,
    FUNDAMENTALS: FUNDAMENTALS_DISCLOSURE_DATE,
}


def record(
    input_class: str,
    as_of,
    *,
    semantics: str | None = None,
    precision: str = "date",
    available: bool = True,
    time_reliable: bool = True,
    missing_reason=None,
    analyst: str | None = None,
    tool: str | None = None,
    call_id: str = "call_001",
) -> dict:
    """One provenance record, defaulting every field to a fresh, valid value.

    ``tool`` defaults to the point-in-time tool that serves the class: freshness
    only judges those, and a statement is grouped by its own tool name.
    """
    if tool is None:
        tool = "get_balance_sheet" if input_class == FUNDAMENTALS else "get_verified_market_snapshot"
    return {
        "analyst": analyst if analyst is not None else input_class,
        "tool": tool,
        "call_id": call_id,
        "input_class": input_class,
        "as_of": as_of,
        "precision": precision,
        "semantics": semantics if semantics is not None else _SEMANTICS.get(input_class, input_class),
        "available": available,
        "time_reliable": time_reliable,
        "missing_reason": missing_reason,
    }


def all_fresh() -> list[dict]:
    """One fresh record per required class, so other cases vary one thing only."""
    from datetime import date, timedelta

    trade = date.fromisoformat(TRADE_DATE)
    return [
        record(MARKET, str(trade - timedelta(days=1)), call_id="call_m"),
        record(SENTIMENT, str(trade - timedelta(days=2)), call_id="call_s"),
        record(NEWS, str(trade - timedelta(days=1)), call_id="call_n"),
        record(FUNDAMENTALS, str(trade - timedelta(days=30)), call_id="call_f"),
    ]


def state(provenance, trade_date: str = TRADE_DATE) -> dict:
    return {"input_provenance": provenance, "trade_date": trade_date}


def reasons(verdict) -> list[str]:
    return [d["reason"] for d in verdict.details]


# ---------------------------------------------------------------------------
# A. Positive cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFreshInputsPass:
    def test_a_valid_market_observation_date_passes(self):
        verdict = evaluate([record(MARKET, "2026-11-21")], TRADE_DATE, required_classes=(MARKET,))
        assert verdict.passed is True
        assert verdict.reason == "fresh"
        assert verdict.details == ()
        assert verdict.check_name == CHECK_NAME

    def test_a_valid_news_publication_date_passes(self):
        verdict = evaluate([record(NEWS, "2026-11-22")], TRADE_DATE, required_classes=(NEWS,))
        assert verdict.passed is True

    def test_a_valid_sentiment_observation_date_passes(self):
        verdict = evaluate([record(SENTIMENT, "2026-11-20")], TRADE_DATE, required_classes=(SENTIMENT,))
        assert verdict.passed is True

    def test_fundamentals_with_a_valid_disclosure_date_passes(self):
        verdict = evaluate(
            [record(FUNDAMENTALS, "2026-08-01", semantics=FUNDAMENTALS_DISCLOSURE_DATE)],
            TRADE_DATE, required_classes=(FUNDAMENTALS,),
        )
        assert verdict.passed is True

    def test_fundamentals_with_a_valid_fiscal_period_date_passes(self):
        """The fiscal-period date is judged by its own, looser threshold."""
        verdict = evaluate(
            [record(FUNDAMENTALS, "2026-06-30", semantics=FUNDAMENTALS_FISCAL_PERIOD_END)],
            TRADE_DATE, required_classes=(FUNDAMENTALS,),
        )
        assert verdict.passed is True

    def test_date_only_precision_keeps_a_date_and_invents_no_timestamp(self):
        verdict = evaluate(
            [record(MARKET, "2026-11-21", precision="date")], TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is True
        # The date is compared as a date: no timestamp was parsed or reported.
        assert "T" not in verdict.as_dict()["details"].__repr__()

    def test_a_datetime_precision_is_reduced_to_its_date_for_the_age(self):
        """20:00 on the trade date is age 0, not a negative age from the time of day."""
        verdict = evaluate(
            [record(MARKET, "2026-11-23T20:00:00", precision="datetime")],
            TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is True

    def test_multiple_valid_pit_records_all_pass(self):
        verdict = check_freshness(state(all_fresh()))
        assert verdict.passed is True
        assert verdict.rule_version == FRESHNESS_RULE_VERSION == "inv03-v1"


# ---------------------------------------------------------------------------
# B. Negative cases: missing or unusable provenance
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMissingOrUnusableProvenanceFailsClosed:
    def test_missing_input_provenance_fails_closed(self):
        verdict = check_freshness({"trade_date": TRADE_DATE})
        assert verdict.passed is False
        assert verdict.reason == MISSING_PROVENANCE

    def test_a_state_that_is_not_a_mapping_fails_closed(self):
        for bad in (None, "state", 5, [("trade_date", TRADE_DATE)]):
            assert check_freshness(bad).passed is False

    def test_provenance_that_is_not_a_list_fails_closed(self):
        verdict = check_freshness({"input_provenance": {"a": 1}, "trade_date": TRADE_DATE})
        assert verdict.passed is False
        assert verdict.reason == INVALID_PROVENANCE

    def test_a_missing_trade_date_fails_closed(self):
        verdict = check_freshness({"input_provenance": all_fresh()})
        assert verdict.passed is False
        assert verdict.reason == "MISSING_TRADE_DATE"

    def test_an_invalid_trade_date_fails_closed(self):
        verdict = check_freshness(state(all_fresh(), trade_date="23/11/2026"))
        assert verdict.passed is False
        assert verdict.reason == "INVALID_TRADE_DATE"

    def test_a_required_input_class_with_no_record_fails(self):
        provenance = [r for r in all_fresh() if r["input_class"] != FUNDAMENTALS]
        verdict = check_freshness(state(provenance))
        assert verdict.passed is False
        missing = [d for d in verdict.details if d["reason"] == MISSING_REQUIRED_INPUT]
        assert [d["input_class"] for d in missing] == [FUNDAMENTALS]

    def test_a_window_scoped_class_absent_is_not_a_failure(self):
        """News and sentiment are window inputs; their absence is not INV-03's concern."""
        provenance = [r for r in all_fresh() if r["input_class"] != NEWS]
        verdict = check_freshness(state(provenance))
        assert verdict.passed is True

    def test_an_optional_class_absent_is_not_a_failure(self):
        """A run without a sentiment analyst is clean when sentiment is not required."""
        provenance = [r for r in all_fresh() if r["input_class"] != SENTIMENT]
        verdict = check_freshness(state(provenance), required_classes=(MARKET, NEWS, FUNDAMENTALS))
        assert verdict.passed is True

    def test_a_missing_as_of_fails(self):
        verdict = evaluate(
            [record(MARKET, None, time_reliable=False)], TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is False
        assert reasons(verdict) == [UNRELIABLE_TIME]

    def test_as_of_none_on_a_record_claiming_reliable_time_fails(self):
        """The contract says as_of=None implies time_reliable=False; if it is not, refuse."""
        verdict = evaluate(
            [record(MARKET, None, time_reliable=True)], TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is False
        assert reasons(verdict) == [MISSING_AS_OF]

    def test_time_reliable_false_fails(self):
        verdict = evaluate(
            [record(NEWS, "2026-11-22", time_reliable=False)], TRADE_DATE, required_classes=(NEWS,),
        )
        assert verdict.passed is False
        assert verdict.reason == UNRELIABLE_TIME
        assert verdict.details[0]["call_id"] == "call_001"

    def test_an_unreliable_record_is_reported_before_its_date_is_judged(self):
        """An unreliable time has no trustworthy age, so the reason is the flag, not the date."""
        verdict = evaluate(
            [record(MARKET, "not-a-date", time_reliable=False)], TRADE_DATE, required_classes=(MARKET,),
        )
        assert reasons(verdict) == [UNRELIABLE_TIME]

    def test_available_false_on_a_required_input_fails(self):
        verdict = evaluate(
            [record(MARKET, None, available=False, time_reliable=False, missing_reason="vendor_unavailable")],
            TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is False
        assert verdict.reason == UNAVAILABLE
        assert "vendor_unavailable" in verdict.details[0]["message"]

    def test_an_invalid_date_fails(self):
        for bad in ("2026-13-01", "2026-11-31", "23-11-2026", "2026/11/22", "not a date", ""):
            verdict = evaluate([record(MARKET, bad)], TRADE_DATE, required_classes=(MARKET,))
            assert verdict.passed is False, bad
            assert verdict.reason == INVALID_DATE, bad

    def test_a_date_normalised_loosely_is_not_guessed_at(self):
        """'2026-7-3' compares as text later than '2026-07-23', so it is refused."""
        verdict = evaluate([record(MARKET, "2026-7-3")], TRADE_DATE, required_classes=(MARKET,))
        assert verdict.passed is False
        assert verdict.reason == INVALID_DATE

    def test_a_datetime_value_at_date_precision_is_refused(self):
        verdict = evaluate(
            [record(MARKET, "2026-11-21T09:30:00", precision="date")],
            TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is False
        assert verdict.reason == INVALID_DATE

    def test_an_invalid_precision_fails(self):
        verdict = evaluate(
            [record(MARKET, "2026-11-21", precision="timestamp")], TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is False
        assert verdict.reason == "INVALID_PRECISION"

    def test_a_future_date_fails(self):
        verdict = evaluate([record(MARKET, "2026-11-24")], TRADE_DATE, required_classes=(MARKET,))
        assert verdict.passed is False
        assert verdict.reason == FUTURE_DATED
        assert verdict.details[0]["actual_age_days"] == 1

    def test_stale_market_data_fails(self):
        verdict = evaluate([record(MARKET, "2026-11-19")], TRADE_DATE, required_classes=(MARKET,))
        assert verdict.passed is False
        assert verdict.reason == STALE_INPUT
        assert verdict.details[0]["actual_age_days"] == 4
        assert verdict.details[0]["threshold_days"] == 3

    def test_stale_news_data_fails(self):
        verdict = evaluate([record(NEWS, "2026-11-20")], TRADE_DATE, required_classes=(NEWS,))
        assert verdict.passed is False
        assert verdict.reason == STALE_INPUT
        assert verdict.details[0]["threshold_days"] == 2

    def test_stale_sentiment_data_fails(self):
        verdict = evaluate([record(SENTIMENT, "2026-11-19")], TRADE_DATE, required_classes=(SENTIMENT,))
        assert verdict.passed is False
        assert verdict.reason == STALE_INPUT

    def test_stale_fundamentals_disclosure_date_fails(self):
        verdict = evaluate(
            [record(FUNDAMENTALS, "2026-07-25", semantics=FUNDAMENTALS_DISCLOSURE_DATE)],
            TRADE_DATE, required_classes=(FUNDAMENTALS,),
        )
        assert verdict.passed is False
        assert verdict.reason == STALE_INPUT
        assert verdict.details[0]["actual_age_days"] == 121
        assert verdict.details[0]["semantics"] == FUNDAMENTALS_DISCLOSURE_DATE

    def test_stale_fundamentals_fiscal_period_date_fails(self):
        verdict = evaluate(
            [record(FUNDAMENTALS, "2026-05-26", semantics=FUNDAMENTALS_FISCAL_PERIOD_END)],
            TRADE_DATE, required_classes=(FUNDAMENTALS,),
        )
        assert verdict.passed is False
        assert verdict.reason == STALE_INPUT
        assert verdict.details[0]["actual_age_days"] == 181
        assert verdict.details[0]["semantics"] == FUNDAMENTALS_FISCAL_PERIOD_END

    def test_an_unsupported_semantic_fails(self):
        verdict = evaluate(
            [record(MARKET, "2026-11-21", semantics=NEWS_PUBLICATION_DATE)],
            TRADE_DATE, required_classes=(MARKET,),
        )
        assert verdict.passed is False
        assert verdict.reason == UNSUPPORTED_SEMANTIC

    def test_an_unknown_semantic_fails(self):
        verdict = evaluate(
            [record(NEWS, "2026-11-22", semantics="estimated_from_cache")],
            TRADE_DATE, required_classes=(NEWS,),
        )
        assert verdict.passed is False
        assert verdict.reason == UNSUPPORTED_SEMANTIC

    def test_an_unknown_required_input_class_fails(self):
        verdict = evaluate(
            [record("macro", "2026-11-22")], TRADE_DATE, required_classes=("macro",),
        )
        assert verdict.passed is False
        assert verdict.reason == UNKNOWN_INPUT_CLASS
        # And it is still reported as a required class with no *valid* record.
        assert UNKNOWN_INPUT_CLASS in reasons(verdict)


# ---------------------------------------------------------------------------
# C. Fundamentals: the two temporal references must not be interchangeable
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a_fiscal_period_date_fresh_under_its_own_threshold_is_stale_under_the_disclosure_one():
    """A 150-day-old period end passes as a fiscal period and fails as a disclosure date."""
    as_of = "2026-06-26"                      # 150 days before the trade date
    fiscal = evaluate(
        [record(FUNDAMENTALS, as_of, semantics=FUNDAMENTALS_FISCAL_PERIOD_END)],
        TRADE_DATE, required_classes=(FUNDAMENTALS,),
    )
    disclosure = evaluate(
        [record(FUNDAMENTALS, as_of, semantics=FUNDAMENTALS_DISCLOSURE_DATE)],
        TRADE_DATE, required_classes=(FUNDAMENTALS,),
    )
    assert fiscal.passed is True
    assert disclosure.passed is False
    assert disclosure.details[0]["actual_age_days"] == 150
    assert (fiscal.details, disclosure.details[0]["threshold_days"]) == ((), 120)


@pytest.mark.unit
def test_the_two_fundamentals_thresholds_are_configured_separately():
    assert (DEFAULT_THRESHOLDS_DAYS[(FUNDAMENTALS, FUNDAMENTALS_DISCLOSURE_DATE)]
            < DEFAULT_THRESHOLDS_DAYS[(FUNDAMENTALS, FUNDAMENTALS_FISCAL_PERIOD_END)])


# ---------------------------------------------------------------------------
# D. Multiple records
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a_fresh_record_beside_a_stale_one_still_fails():
    """The invariant is per input: a newer record must not hide an older one."""
    provenance = all_fresh() + [
        record(MARKET, "2026-10-01", call_id="call_old",
               tool="get_verified_market_snapshot"),
    ]
    verdict = check_freshness(state(provenance))
    assert verdict.passed is False
    assert verdict.reason == STALE_INPUT
    stale = [d for d in verdict.details if d["reason"] == STALE_INPUT]
    assert len(stale) == 1
    assert stale[0]["call_id"] == "call_old"
    assert stale[0]["tool"] == "get_verified_market_snapshot"
    assert stale[0]["analyst"] == MARKET


@pytest.mark.unit
def test_every_failing_record_is_collected_not_just_the_first():
    """The classes this module judges are market and the three statements."""
    provenance = all_fresh() + [
        record(MARKET, "2026-10-01", call_id="call_market_old"),
        record(FUNDAMENTALS, "2025-01-01", call_id="call_fund_old",
               semantics=FUNDAMENTALS_FISCAL_PERIOD_END),
    ]
    verdict = check_freshness(state(provenance))
    assert verdict.passed is False
    ids = {d["call_id"] for d in verdict.details}
    assert {"call_market_old", "call_fund_old"} <= ids


@pytest.mark.unit
def test_two_bad_records_of_the_same_class_are_both_reported():
    provenance = all_fresh() + [
        record(MARKET, "2026-09-01", call_id="call_a"),
        record(MARKET, "2026-09-02", call_id="call_b"),
    ]
    stale = [d for d in check_freshness(state(provenance)).details if d["reason"] == STALE_INPUT]
    assert [d["call_id"] for d in stale] == ["call_a", "call_b"]


# ---------------------------------------------------------------------------
# E. Malformed records
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMalformedRecordsAreNotRepaired:
    def test_a_non_mapping_record_fails(self):
        verdict = check_freshness(state(all_fresh() + ["not a record"]))
        assert verdict.passed is False
        assert MALFORMED_RECORD in reasons(verdict)

    @pytest.mark.parametrize("missing", ["analyst", "tool", "call_id", "input_class",
                                         "precision", "semantics", "available",
                                         "time_reliable", "as_of"])
    def test_a_record_missing_a_field_fails(self, missing):
        broken = all_fresh()
        del broken[0][missing]
        verdict = check_freshness(state(broken))
        assert verdict.passed is False
        assert MALFORMED_RECORD in reasons(verdict)

    @pytest.mark.parametrize("field,value", [
        ("available", "false"),        # a string, not a bool
        ("time_reliable", 1),          # an int that is truthy
        ("input_class", 3),
        ("analyst", ""),               # empty is not an identity
        ("precision", None),
    ])
    def test_a_wrongly_typed_field_fails(self, field, value):
        broken = all_fresh()
        broken[0][field] = value
        verdict = check_freshness(state(broken))
        assert verdict.passed is False
        assert MALFORMED_RECORD in reasons(verdict)

    def test_a_string_flag_is_never_read_as_true(self):
        broken = all_fresh()
        broken[3]["time_reliable"] = "False"
        verdict = check_freshness(state(broken))
        assert verdict.passed is False
        assert MALFORMED_RECORD in reasons(verdict)

    def test_a_number_where_a_date_was_expected_fails(self):
        """An int is not a date and is not coerced with str()."""
        broken = all_fresh()
        broken[0]["as_of"] = 20261121
        verdict = check_freshness(state(broken))
        assert verdict.passed is False
        assert verdict.reason == INVALID_DATE


# ---------------------------------------------------------------------------
# F. Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBoundaries:
    def test_age_exactly_at_the_market_threshold_passes(self):
        verdict = evaluate([record(MARKET, "2026-11-20")], TRADE_DATE, required_classes=(MARKET,))
        assert verdict.passed is True

    def test_age_one_over_the_market_threshold_fails(self):
        verdict = evaluate([record(MARKET, "2026-11-19")], TRADE_DATE, required_classes=(MARKET,))
        assert verdict.passed is False
        assert verdict.details[0]["actual_age_days"] == 4

    def test_age_zero_passes(self):
        verdict = evaluate([record(MARKET, TRADE_DATE)], TRADE_DATE, required_classes=(MARKET,))
        assert verdict.passed is True

    def test_news_at_exactly_two_days_passes_and_three_days_fails(self):
        at = evaluate([record(NEWS, "2026-11-21")], TRADE_DATE, required_classes=(NEWS,))
        over = evaluate([record(NEWS, "2026-11-20")], TRADE_DATE, required_classes=(NEWS,))
        assert at.passed is True
        assert over.passed is False and over.details[0]["actual_age_days"] == 3

    def test_fundamentals_disclosure_date_boundary_is_120_days(self):
        at = evaluate([record(FUNDAMENTALS, "2026-07-26", semantics=FUNDAMENTALS_DISCLOSURE_DATE)],
                      TRADE_DATE, required_classes=(FUNDAMENTALS,))
        over = evaluate([record(FUNDAMENTALS, "2026-07-25", semantics=FUNDAMENTALS_DISCLOSURE_DATE)],
                        TRADE_DATE, required_classes=(FUNDAMENTALS,))
        assert at.passed is True
        assert over.passed is False and over.details[0]["actual_age_days"] == 121

    def test_fundamentals_fiscal_period_boundary_is_180_days(self):
        at = evaluate([record(FUNDAMENTALS, "2026-05-27", semantics=FUNDAMENTALS_FISCAL_PERIOD_END)],
                      TRADE_DATE, required_classes=(FUNDAMENTALS,))
        over = evaluate([record(FUNDAMENTALS, "2026-05-26", semantics=FUNDAMENTALS_FISCAL_PERIOD_END)],
                        TRADE_DATE, required_classes=(FUNDAMENTALS,))
        assert at.passed is True
        assert over.passed is False and over.details[0]["actual_age_days"] == 181

    def test_sentiment_boundary_matches_the_market_three_days(self):
        at = evaluate([record(SENTIMENT, "2026-11-20")], TRADE_DATE, required_classes=(SENTIMENT,))
        over = evaluate([record(SENTIMENT, "2026-11-19")], TRADE_DATE, required_classes=(SENTIMENT,))
        assert at.passed is True and over.passed is False


# ---------------------------------------------------------------------------
# G. Threshold configuration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestThresholdConfiguration:
    def test_the_provisional_thresholds_are_the_agreed_numbers(self):
        assert DEFAULT_THRESHOLDS_DAYS == {
            (MARKET, MARKET_OBSERVATION_DATE): 3,
            (SENTIMENT, SENTIMENT_OBSERVATION_DATE): 3,
            (NEWS, NEWS_PUBLICATION_DATE): 2,
            (FUNDAMENTALS, FUNDAMENTALS_DISCLOSURE_DATE): 120,
            (FUNDAMENTALS, FUNDAMENTALS_FISCAL_PERIOD_END): 180,
        }
        assert THRESHOLD_UNIT == "calendar_days"

    def test_a_class_without_a_threshold_fails_closed(self):
        """Removing a pair from the table must fail, not silently pass."""
        thresholds = {k: v for k, v in DEFAULT_THRESHOLDS_DAYS.items()
                      if k[0] != NEWS}
        verdict = evaluate([record(NEWS, "2026-11-22")], TRADE_DATE,
                           required_classes=(NEWS,), thresholds=thresholds)
        assert verdict.passed is False
        assert verdict.reason == NO_THRESHOLD

    def test_a_class_threshold_can_be_retuned_without_touching_the_module(self):
        thresholds = {**DEFAULT_THRESHOLDS_DAYS, (MARKET, MARKET_OBSERVATION_DATE): 1}
        verdict = evaluate([record(MARKET, "2026-11-20")], TRADE_DATE,
                           required_classes=(MARKET,), thresholds=thresholds)
        assert verdict.passed is False
        assert verdict.details[0]["threshold_days"] == 1

    def test_the_default_required_classes_are_the_point_in_time_inputs(self):
        """News and sentiment are window-scoped, so they are not required."""
        assert set(REQUIRED_INPUT_CLASSES) == {MARKET, FUNDAMENTALS}


# ---------------------------------------------------------------------------
# H. The check is deterministic and model-free
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGateIsDeterministicAndModelFree:
    def test_the_result_serialises_to_the_named_shape(self):
        verdict = evaluate([record(MARKET, "2026-09-01", call_id="call_001")],
                           TRADE_DATE, required_classes=(MARKET,))
        as_dict = verdict.as_dict()
        assert as_dict["passed"] is False
        assert as_dict["check_name"] == "INV-03"
        assert as_dict["reason"] == STALE_INPUT
        detail = as_dict["details"][0]
        for key in ("analyst", "tool", "call_id", "input_class", "as_of", "semantics",
                    "threshold_days", "actual_age_days", "reason"):
            assert key in detail
        assert detail["call_id"] == "call_001"
        assert (detail["threshold_days"], detail["actual_age_days"]) == (3, 83)

    def test_the_same_state_always_gives_the_same_verdict(self):
        st = state(all_fresh() + [record(MARKET, "2026-09-01")])
        seen = {repr(check_freshness(st)) for _ in range(5)}
        assert len(seen) == 1

    def test_the_check_does_not_modify_the_state_it_is_given(self):
        st = state(all_fresh())
        before = repr(st)
        check_freshness(st)
        assert repr(st) == before

    def test_the_module_imports_only_the_standard_library(self):
        names = set()
        for node in ast.walk(ast.parse(FRESHNESS_MODULE.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
        assert names == {"__future__", "collections", "dataclasses", "datetime"}

    def test_the_module_calls_no_model_or_vendor(self):
        source = FRESHNESS_MODULE.read_text(encoding="utf-8")
        for forbidden in ("with_structured_output", ".invoke(", "structured_llm",
                          "requests", "yfinance", "langchain", "tradingagents."):
            assert forbidden not in source


# ---------------------------------------------------------------------------
# E. The vocabulary is a contract with the producer
# ---------------------------------------------------------------------------
#
# Every other test builds its records from these same constants, so it passes
# whichever strings the constants hold: it proves the checks are consistent, not
# that they read what teammate C writes. These two pin the values themselves, so
# a rename on either side breaks a test instead of failing silently at run time.

@pytest.mark.unit
class TestTheVocabularyMatchesTheProducer:
    def test_the_class_and_semantic_values_are_the_producers_strings(self):
        """The literals below are what ``analysts/`` records actually carry."""
        assert MARKET == "market_close"
        assert MARKET_OBSERVATION_DATE == "latest_trading_row"
        assert FUNDAMENTALS == "fundamentals"
        assert FUNDAMENTALS_FISCAL_PERIOD_END == "period_end"

    def test_a_record_written_with_the_producers_literals_passes(self):
        """Built without the constants: exactly what C emits today."""
        provenance = [
            {
                "analyst": "market", "tool": "get_verified_market_snapshot",
                "call_id": "c_m", "input_class": "market_close",
                "period_id": "", "as_of": "2026-11-21", "precision": "date",
                "semantics": "latest_trading_row", "evidence": "Latest trading row used: 2026-11-21",
                "available": True, "time_reliable": True, "missing_reason": "",
            },
            {
                "analyst": "fundamentals", "tool": "get_income_statement",
                "call_id": "c_f", "input_class": "fundamentals",
                "period_id": "2026-09-30", "as_of": "2026-09-30", "precision": "date",
                "semantics": "period_end", "evidence": "get_income_statement: 2026-09-30",
                "available": True, "time_reliable": True, "missing_reason": "",
            },
        ]
        verdict = check_freshness(state(provenance))
        assert verdict.passed is True, reasons(verdict)

    def test_the_default_required_classes_are_the_producers_strings(self):
        assert set(REQUIRED_INPUT_CLASSES) == {"market_close", "fundamentals"}
