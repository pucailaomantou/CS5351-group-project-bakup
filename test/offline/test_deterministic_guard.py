"""The deterministic gate: one decision over INV-01, INV-02 and INV-03.

Two kinds of test live here. The aggregation tests use controlled doubles for
the three checks, so a combination of pass/fail/raise can be produced without
finding prose that happens to trip exactly two rules. The integration tests run
the *real* checks against hand-built state, so the gate is proved against the
modules it will actually call.

The gate is judged on its decision — ``passed``, ``final_rating``, and the entry
for each check — not on truthiness. A gate that returns REVIEW for the wrong
reason, or that keeps a rating after a veto, is as wrong as one that passes.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

import tradingagents.safety.deterministic_guard as dg
from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating, render_pm_decision
from tradingagents.safety.freshness import (
    FRESHNESS_RULE_VERSION,
    FreshnessVerdict,
    MALFORMED_RECORD,
    STALE_INPUT,
)
from tradingagents.safety.guard import GUARD_RULE_VERSION, RATING_REVIEW, GuardVerdict
from tradingagents.safety.sizing import SIZING_RULE_VERSION, SizingVerdict
from tradingagents.safety.deterministic_guard import (
    AGGREGATE_RULE_VERSION,
    CHECK_INV01,
    CHECK_INV02,
    CHECK_INV03,
    CHECK_ORDER,
    OUTCOME_EXECUTION_ERROR,
    OUTCOME_PASS,
    OUTCOME_VALIDATION_FAILURE,
    REASON_EXECUTION_ERROR,
    DeterministicGuardResult,
    evaluate_guard,
)

GATE_MODULE = (
    Path(__file__).resolve().parents[2] / "src" / "tradingagents" / "safety" / "deterministic_guard.py"
)

TRADE_DATE = "2026-11-23"


# ---------------------------------------------------------------------------
# Fixtures: a state whose every check passes, and controlled doubles
# ---------------------------------------------------------------------------

def record(input_class: str, as_of, *, semantics: str, cid: str = "c1") -> dict:
    """One fresh provenance record; the fields INV-03 requires and no more."""
    return {
        "analyst": input_class,
        "tool": "get_data",
        "call_id": cid,
        "input_class": input_class,
        "as_of": as_of,
        "precision": "date",
        "semantics": semantics,
        "available": True,
        "time_reliable": True,
        "missing_reason": None,
    }


def fresh_provenance() -> list[dict]:
    """One fresh record per required input class."""
    return [
        record("market", "2026-11-21", semantics="market_observation_date", cid="c_m"),
        record("sentiment", "2026-11-21", semantics="sentiment_observation_date", cid="c_s"),
        record("news", "2026-11-22", semantics="news_publication_date", cid="c_n"),
        record("fundamentals", "2026-08-01", semantics="fundamentals_disclosure_date", cid="c_f"),
    ]


def decision(executive_summary: str, rating: PortfolioRating = PortfolioRating.BUY) -> str:
    """A decision rendered by the pipeline's own renderer."""
    return render_pm_decision(
        PortfolioDecision(
            rating=rating,
            executive_summary=executive_summary,
            investment_thesis="Backlog intact.",
        )
    )


def passing_state(rating: str = "Buy") -> dict:
    """A state on which the real INV-01, INV-02 and INV-03 all pass."""
    return {
        "final_rating": rating,
        "final_trade_decision": decision("Enter 5% of the portfolio."),
        "input_provenance": fresh_provenance(),
        "trade_date": TRADE_DATE,
    }


# --- Doubles: the checks the aggregator calls, replaced one at a time --------

OK_GUARD = GuardVerdict(passed=True, rating="Buy", reason="canonical_rating",
                        rule_version=GUARD_RULE_VERSION)
OK_SIZING = SizingVerdict(True, 5.0, "within_cap", rule_version=SIZING_RULE_VERSION)
OK_FRESH = FreshnessVerdict(passed=True)


@pytest.fixture
def checks(monkeypatch):
    """Replace the three checks; ``checks.set(...)`` swaps one out per test."""

    class Checks:
        def __init__(self):
            self.values = {
                CHECK_INV01: lambda _: OK_GUARD,
                CHECK_INV02: lambda _: OK_SIZING,
                CHECK_INV03: lambda _: OK_FRESH,
            }

        def set(self, check_name, fn):
            self.values[check_name] = fn
            return self

    installed = Checks()

    def dispatch(check_name):
        return lambda arg: installed.values[check_name](arg)

    monkeypatch.setattr(dg, "check_rating", dispatch(CHECK_INV01))
    monkeypatch.setattr(dg, "check_position_size", dispatch(CHECK_INV02))
    monkeypatch.setattr(dg, "check_freshness", dispatch(CHECK_INV03))
    return installed


# ---------------------------------------------------------------------------
# A. All checks pass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAllChecksPass:
    def test_the_original_rating_is_preserved(self):
        """Against the real checks: the caller's rating is published unchanged."""
        result = evaluate_guard(passing_state("Overweight"))
        assert result.passed is True
        assert result.final_rating == "Overweight"

    def test_the_published_rating_comes_from_the_inv01_entry(self, checks):
        """Under doubles, whatever INV-01 published is what is published."""
        checks.set(CHECK_INV01, lambda _: GuardVerdict(True, "Hold", "canonical_rating"))
        result = evaluate_guard(passing_state())
        assert result.passed is True
        assert result.final_rating == "Hold"
        assert result.checks[CHECK_INV01]["details"]["rating"] == "Hold"

    def test_every_check_entry_reports_pass(self, checks):
        result = evaluate_guard(passing_state())
        assert set(result.checks) == {CHECK_INV01, CHECK_INV02, CHECK_INV03}
        assert all(entry["outcome"] == OUTCOME_PASS for entry in result.checks.values())
        assert all(entry["passed"] is True for entry in result.checks.values())

    @pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell"])
    def test_each_tradeable_rating_survives_a_clean_run(self, rating):
        """Against the real checks, not the doubles."""
        result = evaluate_guard(passing_state(rating))
        assert result.passed is True
        assert result.final_rating == rating

    def test_the_aggregate_records_its_own_rule_version(self, checks):
        assert evaluate_guard(passing_state()).rule_version == AGGREGATE_RULE_VERSION == "agg-v1"


# ---------------------------------------------------------------------------
# B-D. One check fails, the others pass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEachSingleVetoIsFinal:
    def test_an_inv01_veto_forces_review(self, checks):
        checks.set(CHECK_INV01, lambda _: GuardVerdict(False, RATING_REVIEW, "out_of_enum"))
        result = evaluate_guard(passing_state())
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW
        assert result.checks[CHECK_INV01]["reason"] == "out_of_enum"
        # The two checks that passed are still reported as having passed.
        assert result.checks[CHECK_INV02]["passed"] is True
        assert result.checks[CHECK_INV03]["passed"] is True

    def test_an_inv02_veto_forces_review(self, checks):
        checks.set(CHECK_INV02, lambda _: SizingVerdict(False, None, "over_cap", "12% > 10%"))
        result = evaluate_guard(passing_state())
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW
        assert result.checks[CHECK_INV02]["details"] == {"percent": None, "detail": "12% > 10%"}

    def test_an_inv03_veto_forces_review(self, checks):
        stale = FreshnessVerdict(
            passed=False, reason=STALE_INPUT,
            details=({"analyst": "market", "call_id": "c_old", "reason": STALE_INPUT,
                      "threshold_days": 3, "actual_age_days": 20},),
        )
        checks.set(CHECK_INV03, lambda _: stale)
        result = evaluate_guard(passing_state())
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW
        assert result.checks[CHECK_INV03]["details"]["failures"][0]["call_id"] == "c_old"

    @pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell"])
    def test_no_tradeable_rating_is_ever_published_after_a_veto(self, checks, rating):
        """The vetoed rating must never be returned as the approved one."""
        checks.set(CHECK_INV02, lambda _: SizingVerdict(False, None, "over_cap", "80% > 10%"))
        result = evaluate_guard(passing_state(rating))
        assert result.final_rating == RATING_REVIEW
        assert result.final_rating != rating


# ---------------------------------------------------------------------------
# E. Multiple failures are all retained
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEveryFailureIsRetained:
    def test_two_vetoes_are_both_in_the_output(self, checks):
        checks.set(CHECK_INV01, lambda _: GuardVerdict(False, RATING_REVIEW, "missing_or_empty"))
        checks.set(CHECK_INV02, lambda _: SizingVerdict(False, None, "unparseable_sizing", "all_in"))
        result = evaluate_guard(passing_state())
        assert result.passed is False
        failed = [name for name in CHECK_ORDER if result.checks[name]["passed"] is False]
        assert failed == [CHECK_INV01, CHECK_INV02]
        assert result.checks[CHECK_INV03]["passed"] is True

    def test_all_three_vetoes_are_retained(self):
        """Against the real checks: no rating, no size, no provenance."""
        result = evaluate_guard({})
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW
        assert all(result.checks[name]["passed"] is False for name in CHECK_ORDER)
        assert result.checks[CHECK_INV01]["reason"] == "missing_or_empty"
        assert result.checks[CHECK_INV02]["reason"] == "not_text"
        assert result.checks[CHECK_INV03]["reason"] == "MISSING_TRADE_DATE"


# ---------------------------------------------------------------------------
# F. The audit output
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAuditOutput:
    def test_every_entry_has_the_same_envelope(self, checks):
        result = evaluate_guard(passing_state())
        for name, entry in result.checks.items():
            assert set(entry) == {"passed", "check_name", "reason", "rule_version",
                                  "outcome", "details"}, name
            assert entry["check_name"] == name

    def test_reason_codes_and_rule_versions_are_preserved_verbatim(self):
        result = evaluate_guard({
            "final_rating": "Buy",
            "final_trade_decision": decision("12% of the portfolio."),
            "input_provenance": fresh_provenance(),
            "trade_date": TRADE_DATE,
        })
        assert result.checks[CHECK_INV01]["reason"] == "canonical_rating"
        assert result.checks[CHECK_INV01]["rule_version"] == GUARD_RULE_VERSION
        assert result.checks[CHECK_INV02]["reason"] == "over_cap"
        assert result.checks[CHECK_INV02]["rule_version"] == SIZING_RULE_VERSION
        assert result.checks[CHECK_INV03]["rule_version"] == FRESHNESS_RULE_VERSION

    def test_inv03_per_input_evidence_survives(self):
        stale = fresh_provenance() + [record("market", "2026-10-01",
                                             semantics="market_observation_date", cid="c_old")]
        result = evaluate_guard({
            "final_rating": "Buy",
            "final_trade_decision": decision("Enter 5% of the portfolio."),
            "input_provenance": stale,
            "trade_date": TRADE_DATE,
        })
        failures = result.checks[CHECK_INV03]["details"]["failures"]
        old = [f for f in failures if f["call_id"] == "c_old"]
        assert len(old) == 1
        for key in ("analyst", "tool", "call_id", "input_class", "as_of", "semantics",
                    "threshold_days", "actual_age_days", "reason"):
            assert key in old[0]
        assert (old[0]["threshold_days"], old[0]["actual_age_days"]) == (3, 53)

    def test_the_whole_result_is_json_serialisable(self):
        stale = fresh_provenance() + [record("market", "2026-10-01",
                                             semantics="market_observation_date", cid="c_old")]
        result = evaluate_guard({
            "final_rating": "Strong Buy",
            "final_trade_decision": decision("All in."),
            "input_provenance": stale,
            "trade_date": TRADE_DATE,
        })
        dumped = json.dumps(result.as_dict())
        assert '"final_rating": "REVIEW"' in dumped
        # A tuple anywhere would have raised; parse it back to be sure.
        assert json.loads(dumped)["checks"][CHECK_INV03]["details"]["failures"]

    def test_as_dict_keeps_a_fixed_key_order(self, checks):
        a = list(evaluate_guard(passing_state()).as_dict())
        assert a == ["passed", "final_rating", "rule_version", "checks"]
        assert list(evaluate_guard(passing_state()).as_dict()["checks"]) == list(CHECK_ORDER)

    def test_a_vetoed_percent_is_reported_as_null_not_zero(self):
        result = evaluate_guard({
            "final_rating": "Buy",
            "final_trade_decision": decision("80% of the portfolio."),
            "input_provenance": fresh_provenance(),
            "trade_date": TRADE_DATE,
        })
        assert result.checks[CHECK_INV02]["details"]["percent"] is None
        assert "80%" in result.checks[CHECK_INV02]["details"]["detail"]


# ---------------------------------------------------------------------------
# Execution errors, distinct from validation failures
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExecutionErrorsFailClosed:
    def test_a_check_that_raises_marks_an_execution_error(self, checks):
        def boom(_):
            raise RuntimeError("vendor client exploded")
        checks.set(CHECK_INV02, boom)
        result = evaluate_guard(passing_state())
        entry = result.checks[CHECK_INV02]
        assert entry["passed"] is False
        assert entry["outcome"] == OUTCOME_EXECUTION_ERROR
        assert entry["reason"] == REASON_EXECUTION_ERROR
        assert entry["details"] == {"error_type": "RuntimeError",
                                    "error_message": "vendor client exploded"}
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW

    def test_an_execution_error_is_distinguishable_from_a_veto(self, checks):
        checks.set(CHECK_INV01, lambda _: GuardVerdict(False, RATING_REVIEW, "out_of_enum"))
        checks.set(CHECK_INV02, lambda _: (_ for _ in ()).throw(ValueError("bad")))
        result = evaluate_guard(passing_state())
        assert result.checks[CHECK_INV01]["outcome"] == OUTCOME_VALIDATION_FAILURE
        assert result.checks[CHECK_INV02]["outcome"] == OUTCOME_EXECUTION_ERROR
        assert result.checks[CHECK_INV01]["reason"] != REASON_EXECUTION_ERROR
        assert result.checks[CHECK_INV02]["reason"] == REASON_EXECUTION_ERROR

    def test_the_remaining_checks_still_run_after_one_raises(self, checks):
        calls = []

        def boom(name):
            calls.append(name)
            raise RuntimeError(name)

        checks.set(CHECK_INV01, lambda _: boom(CHECK_INV01))
        result = evaluate_guard(passing_state())
        # INV-02 and INV-03 were invoked and reported even though INV-01 crashed.
        assert result.checks[CHECK_INV02]["passed"] is True
        assert result.checks[CHECK_INV03]["passed"] is True
        assert calls == [CHECK_INV01]

    def test_an_execution_error_is_never_reported_as_a_pass(self, checks):
        checks.set(CHECK_INV03, lambda _: (_ for _ in ()).throw(KeyError("x")))
        result = evaluate_guard(passing_state())
        assert result.checks[CHECK_INV03]["passed"] is False
        assert result.passed is False

    def test_an_execution_error_survives_serialisation(self, checks):
        checks.set(CHECK_INV01, lambda _: (_ for _ in ()).throw(TypeError("odd type")))
        dumped = json.dumps(evaluate_guard(passing_state()).as_dict())
        entry = json.loads(dumped)["checks"][CHECK_INV01]
        assert entry["outcome"] == OUTCOME_EXECUTION_ERROR
        assert entry["details"]["error_type"] == "TypeError"


# ---------------------------------------------------------------------------
# G. No accidental side effects
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNoAccidentalBehaviourChanges:
    def test_the_input_state_is_not_modified(self):
        state = passing_state()
        before = repr(state)
        evaluate_guard(state)
        assert repr(state) == before

    def test_mutating_the_output_does_not_reach_the_verdicts(self, checks):
        """Entries are fresh dicts, so a caller cannot alter a check's verdict."""
        result = evaluate_guard(passing_state())
        result.checks[CHECK_INV01]["details"]["rating"] = "Sell"
        assert result.checks[CHECK_INV01]["details"]["rating"] == "Sell"
        # A second run is unaffected, and the module-level doubles are untouched.
        assert evaluate_guard(passing_state()).checks[CHECK_INV01]["details"]["rating"] == "Buy"

    def test_the_result_is_frozen(self, checks):
        result = evaluate_guard(passing_state())
        with pytest.raises(Exception):
            result.passed = False
        assert result.passed is True

    def test_the_result_type_is_its_own(self, checks):
        assert isinstance(evaluate_guard(passing_state()), DeterministicGuardResult)

    def test_the_gate_calls_the_real_modules_not_copies_of_their_rules(self):
        """Static scan: the cap, the rating enum and the thresholds live elsewhere."""
        source = GATE_MODULE.read_text(encoding="utf-8")
        for duplicated in (
            "MAX_POSITION_PCT", "TRADEABLE_RATINGS", "DEFAULT_THRESHOLDS_DAYS",
            "RATINGS_5_TIER", "10.0", "180",
        ):
            assert duplicated not in source, duplicated

    def test_the_gate_imports_the_three_checks_and_nothing_model_backed(self):
        names = set()
        for node in ast.walk(ast.parse(GATE_MODULE.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
        assert names == {"__future__", "collections", "copy", "dataclasses", "tradingagents"}

    def test_the_gate_writes_nothing_back_to_the_graph(self):
        """No graph wiring and no write-back: the gate is a pure function."""
        source = GATE_MODULE.read_text(encoding="utf-8")
        for forbidden in ("add_node", "add_edge", "langgraph",
                          "with_structured_output", ".invoke(",
                          "from tradingagents.agents", "from tradingagents.graph"):
            assert forbidden not in source, forbidden

    def test_the_same_state_always_gives_the_same_result(self):
        state = passing_state()
        seen = {repr(evaluate_guard(state).as_dict()) for _ in range(5)}
        assert len(seen) == 1


# ---------------------------------------------------------------------------
# Integration: the real checks, driven by real state shapes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAgainstTheRealChecks:
    def test_a_clean_run_passes_end_to_end(self):
        result = evaluate_guard(passing_state())
        assert result.passed is True
        assert result.final_rating == "Buy"

    def test_a_real_over_cap_size_vetoes(self):
        """INV-02's own fit criterion, reached through the gate."""
        state = passing_state()
        state["final_trade_decision"] = decision("12% of portfolio")
        result = evaluate_guard(state)
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW
        assert result.checks[CHECK_INV02]["reason"] == "over_cap"

    def test_a_real_review_rating_vetoes(self):
        state = passing_state()
        state["final_rating"] = "REVIEW"
        result = evaluate_guard(state)
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW
        assert result.checks[CHECK_INV01]["reason"] == "review_not_tradeable"

    def test_real_malformed_provenance_is_reported_per_record(self):
        state = passing_state()
        state["input_provenance"] = fresh_provenance() + [{"input_class": "market"}]
        result = evaluate_guard(state)
        assert result.passed is False
        reasons = [f["reason"] for f in result.checks[CHECK_INV03]["details"]["failures"]]
        assert MALFORMED_RECORD in reasons

    def test_a_missing_trade_date_fails_closed(self):
        state = passing_state()
        del state["trade_date"]
        result = evaluate_guard(state)
        assert result.passed is False
        assert result.checks[CHECK_INV03]["reason"] == "MISSING_TRADE_DATE"

    def test_a_state_without_provenance_fails_closed(self):
        """Today's real state: ``input_provenance`` does not exist yet."""
        result = evaluate_guard({"final_rating": "Buy",
                                 "final_trade_decision": decision("Enter 5% of the portfolio."),
                                 "trade_date": TRADE_DATE})
        assert result.passed is False
        assert result.checks[CHECK_INV03]["reason"] == "MISSING_PROVENANCE"

    def test_each_tradeable_tier_survives_a_clean_run(self):
        for rating in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
            assert evaluate_guard(passing_state(rating)).final_rating == rating


# ---------------------------------------------------------------------------
# State extraction must never crash the gate
# ---------------------------------------------------------------------------

class _RaisingMapping(Mapping):
    """A Mapping whose ``.get`` raises, as a broken state wrapper would.

    ``Mapping`` supplies ``get`` via ``__getitem__``; overriding ``get`` here
    models a wrapper that queries an unreadable store. Every other read is
    delegated so the class is a genuine ``Mapping``.
    """

    def __init__(self, error=RuntimeError("state store unreadable")):
        self._error = error

    def __getitem__(self, key):
        raise self._error

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def get(self, key, default=None):
        raise self._error


@pytest.mark.unit
class TestBrokenStateExtractionFailsClosed:
    """A state the gate cannot read is an execution error, never a crash."""

    def test_a_mapping_whose_get_raises_does_not_propagate(self):
        result = evaluate_guard(_RaisingMapping())  # must not raise
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW

    def test_every_check_is_recorded_as_an_execution_error(self):
        result = evaluate_guard(_RaisingMapping())
        assert set(result.checks) == set(CHECK_ORDER)
        for name in CHECK_ORDER:
            entry = result.checks[name]
            assert entry["passed"] is False
            assert entry["outcome"] == OUTCOME_EXECUTION_ERROR
            assert entry["reason"] == REASON_EXECUTION_ERROR
            assert entry["check_name"] == name

    def test_the_extraction_error_is_named_in_the_audit(self):
        result = evaluate_guard(_RaisingMapping())
        for name in CHECK_ORDER:
            assert result.checks[name]["details"] == {
                "error_type": "RuntimeError",
                "error_message": "state store unreadable",
            }

    def test_any_exception_type_from_get_is_caught(self):
        for error in (KeyError("k"), ValueError("v"), OSError("io"), TypeError("t")):
            result = evaluate_guard(_RaisingMapping(error))
            assert result.passed is False, error
            assert result.checks[CHECK_INV01]["details"]["error_type"] == type(error).__name__

    def test_a_broken_state_still_serialises(self):
        dumped = json.dumps(evaluate_guard(_RaisingMapping()).as_dict())
        parsed = json.loads(dumped)
        assert parsed["passed"] is False
        assert parsed["final_rating"] == "REVIEW"
        assert set(parsed["checks"]) == set(CHECK_ORDER)

    @pytest.mark.parametrize("bad", [None, "state", 5, 3.5, True, [], ["trade_date"], object()])
    def test_a_non_mapping_state_fails_closed_without_raising(self, bad):
        """The existing safe path is preserved: per-check reasons, no exception."""
        result = evaluate_guard(bad)
        assert result.passed is False
        assert result.final_rating == RATING_REVIEW
        # Each check fails for its own reason, not as an execution error.
        assert all(entry["outcome"] == OUTCOME_VALIDATION_FAILURE
                   for entry in result.checks.values())

    def test_an_empty_mapping_is_a_validation_failure_not_an_error(self):
        result = evaluate_guard({})
        assert result.checks[CHECK_INV01]["reason"] == "missing_or_empty"
        assert result.checks[CHECK_INV02]["reason"] == "not_text"
        assert all(e["outcome"] == OUTCOME_VALIDATION_FAILURE for e in result.checks.values())


# ---------------------------------------------------------------------------
# as_dict() must hand out independent copies
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAsDictReturnsIndependentCopies:
    def _vetoed(self):
        """A failed result, so INV-03 carries a non-empty ``failures`` list."""
        stale = fresh_provenance() + [record("market", "2026-10-01",
                                             semantics="market_observation_date", cid="c_old")]
        return evaluate_guard({
            "final_rating": "Buy",
            "final_trade_decision": decision("12% of the portfolio."),
            "input_provenance": stale,
            "trade_date": TRADE_DATE,
        })

    def test_editing_an_inv01_detail_does_not_touch_the_result(self):
        result = evaluate_guard(passing_state())
        out = result.as_dict()
        out["checks"][CHECK_INV01]["details"]["rating"] = "Sell"
        assert result.checks[CHECK_INV01]["details"]["rating"] == "Buy"

    def test_editing_an_inv02_detail_does_not_touch_the_result(self):
        result = self._vetoed()
        before = dict(result.checks[CHECK_INV02]["details"])
        out = result.as_dict()
        out["checks"][CHECK_INV02]["details"]["detail"] = "tampered"
        assert result.checks[CHECK_INV02]["details"] == before

    def test_appending_to_inv03_failures_does_not_touch_the_result(self):
        result = self._vetoed()
        before = len(result.checks[CHECK_INV03]["details"]["failures"])
        assert before > 0
        out = result.as_dict()
        out["checks"][CHECK_INV03]["details"]["failures"].append({"reason": "TAMPERED"})
        assert len(result.checks[CHECK_INV03]["details"]["failures"]) == before

    def test_editing_a_nested_failure_dict_does_not_touch_the_result(self):
        result = self._vetoed()
        original = result.checks[CHECK_INV03]["details"]["failures"][0]["reason"]
        out = result.as_dict()
        out["checks"][CHECK_INV03]["details"]["failures"][0]["reason"] = "TAMPERED"
        assert result.checks[CHECK_INV03]["details"]["failures"][0]["reason"] == original

    def test_a_second_call_returns_the_original_unmodified_data(self):
        result = self._vetoed()
        first = result.as_dict()
        first["checks"][CHECK_INV01]["details"]["rating"] = "Sell"
        first["checks"][CHECK_INV03]["details"]["failures"].clear()
        second = result.as_dict()
        assert second["checks"][CHECK_INV01]["details"]["rating"] == "Buy"
        assert len(second["checks"][CHECK_INV03]["details"]["failures"]) > 0
        assert second == result.as_dict()

    def test_two_calls_share_no_mutable_objects(self):
        result = self._vetoed()
        a, b = result.as_dict(), result.as_dict()
        a["checks"][CHECK_INV03]["details"]["failures"].append({"reason": "x"})
        assert b["checks"][CHECK_INV03]["details"]["failures"] != a["checks"][CHECK_INV03]["details"]["failures"]

    def test_mutating_the_result_entry_does_not_touch_the_next_dict(self):
        """The copy protects both directions: result entry -> as_dict output."""
        result = evaluate_guard(passing_state())
        before = result.as_dict()
        result.checks[CHECK_INV01]["details"]["rating"] = "Sell"
        after = result.as_dict()
        assert after["checks"][CHECK_INV01]["details"]["rating"] == "Sell"
        # The earlier snapshot is an independent copy, so it kept the old value.
        assert before["checks"][CHECK_INV01]["details"]["rating"] == "Buy"
