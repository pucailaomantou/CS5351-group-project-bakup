"""INV-01: the guard accepts exactly six ratings and never trades REVIEW.

These tests judge the guard on its own, not through ``parse_rating`` or
``is_review``: the point of the boundary is that it does not trust the upstream
readers, so a test that asked them for the expected answer would prove nothing
about it. Each case below states the value and what the guard must do with it.

The repository has no position mapper, so the "REVIEW is not mapped to a
position" clause is tested at the guard's own refusal boundary
(``require_tradeable``), which is where such a mapper would have to call.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tradingagents.safety.guard import (
    CANONICAL_RATINGS,
    GUARD_RULE_VERSION,
    RATING_REVIEW,
    TRADEABLE_RATINGS,
    check_rating,
    require_tradeable,
)

GUARD_MODULE = Path(__file__).resolve().parents[2] / "src" / "tradingagents" / "safety" / "guard.py"

# Names that would let a model influence the verdict. Absent from the guard's
# imports, the gate cannot call one.
LLM_IMPORTS = {
    "langchain", "langchain_core", "langchain_openai", "langchain_anthropic",
    "langgraph", "openai", "anthropic", "google", "transformers", "ollama",
    "tradingagents",
}


def _module_imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


# --- A. Rating enum closure -------------------------------------------------

@pytest.mark.unit
class TestCanonicalTradeableRatingsPass:
    @pytest.mark.parametrize("rating", TRADEABLE_RATINGS)
    def test_each_canonical_tradeable_rating_passes(self, rating):
        verdict = check_rating(rating)
        assert verdict.passed is True
        assert verdict.rating == rating
        assert verdict.tradeable is True
        assert verdict.reason == "canonical_rating"

    @pytest.mark.parametrize("rating", TRADEABLE_RATINGS)
    def test_surrounding_whitespace_is_normalised_not_rejected(self, rating):
        for padded in (f" {rating}", f"{rating} ", f"\t{rating}\n", f"  {rating}  "):
            assert check_rating(padded).rating == rating
            assert check_rating(padded).passed is True

    def test_the_tradeable_set_is_exactly_the_five_tiers(self):
        assert set(TRADEABLE_RATINGS) == {"Buy", "Overweight", "Hold", "Underweight", "Sell"}

    def test_the_canonical_set_is_the_five_tiers_plus_review(self):
        assert CANONICAL_RATINGS == set(TRADEABLE_RATINGS) | {RATING_REVIEW}
        assert len(CANONICAL_RATINGS) == 6


@pytest.mark.unit
class TestCanonicalReviewIsVetoed:
    def test_review_is_recognised_and_vetoed(self):
        verdict = check_rating("REVIEW")
        assert verdict.passed is False
        assert verdict.rating == RATING_REVIEW
        assert verdict.tradeable is False
        assert verdict.reason == "review_not_tradeable"

    @pytest.mark.parametrize("spelling", ["review", "Review", "ReViEw", " REVIEW ", "\treview\n"])
    def test_review_is_recognised_in_any_case_or_padding(self, spelling):
        verdict = check_rating(spelling)
        assert verdict.passed is False
        assert verdict.rating == RATING_REVIEW
        assert verdict.reason == "review_not_tradeable"


@pytest.mark.unit
class TestInvalidValuesFailClosedToReview:
    @pytest.mark.parametrize("value", [
        "Strong Buy",            # a heavier Buy is not the Buy tier
        "overweight plus",       # bare, lowercase variant
        "Overweight Plus",       # the variant a first-word regex would misread
        "",                      # empty string
        None,                    # missing
        "Not a rating at all",   # arbitrary prose
        "BUY",                   # case variant must not widen the enum
        "Hold.",                 # trailing punctuation is not the enum value
        "Sell-side",             # token that merely starts with a tier
    ])
    def test_invalid_value_resolves_to_review(self, value):
        verdict = check_rating(value)
        assert verdict.passed is False
        assert verdict.rating == RATING_REVIEW
        assert verdict.tradeable is False

    @pytest.mark.parametrize("value", ["Strong Buy", "overweight plus", "Overweight Plus", ""])
    def test_the_inv01_injection_values_are_vetoed(self, value):
        """The four strings INV-01 names, decided by the guard itself."""
        assert check_rating(value).rating == RATING_REVIEW

    @pytest.mark.parametrize("value", ["   ", "\n\t ", "\u00a0"])
    def test_whitespace_only_is_missing(self, value):
        verdict = check_rating(value)
        assert verdict.passed is False
        assert verdict.rating == RATING_REVIEW
        assert verdict.reason == "missing_or_empty"

    def test_an_unknown_value_is_never_converted_to_a_valid_rating(self):
        """Fail-closed means REVIEW, not the nearest tier."""
        for value in ("Strong Buy", "Overweight Plus", "buy", "sell now"):
            assert check_rating(value).rating not in TRADEABLE_RATINGS


# --- C. Deterministic boundary and action control ---------------------------

@pytest.mark.unit
class TestFailClosedOnMissingOrMalformedInput:
    @pytest.mark.parametrize("value", [None, "", "   ", "\n"])
    def test_missing_or_empty_fails_closed(self, value):
        verdict = check_rating(value)
        assert verdict.passed is False
        assert verdict.rating == RATING_REVIEW

    @pytest.mark.parametrize("value", [None, 42, 3.14, True, [], {}, object()])
    def test_wrong_or_unexpected_type_fails_closed(self, value):
        """A non-string is not a rating; it is not coerced with str() either."""
        verdict = check_rating(value)
        assert verdict.passed is False
        assert verdict.rating == RATING_REVIEW
        assert verdict.reason == "missing_or_empty"

    def test_no_argument_like_empty_state_value_can_bypass(self):
        """A pre-parsed non-empty value is validated like any other input."""
        for supplied in ("Strong Buy", "REVIEW", "Overweight Plus"):
            assert check_rating(supplied).rating == RATING_REVIEW


@pytest.mark.unit
class TestReviewCannotBeMappedToAPosition:
    """No position mapper exists in the repo, so the refusal boundary is the test."""

    @pytest.mark.parametrize("spelling", ["REVIEW", "review", " REVIEW "])
    def test_mapping_review_is_refused(self, spelling):
        with pytest.raises(ValueError):
            require_tradeable(spelling)

    @pytest.mark.parametrize("value", ["Strong Buy", "Overweight Plus", "", None])
    def test_mapping_an_invalid_rating_is_refused(self, value):
        with pytest.raises(ValueError):
            require_tradeable(value)

    @pytest.mark.parametrize("rating", TRADEABLE_RATINGS)
    def test_mapping_a_canonical_rating_returns_it_normalised(self, rating):
        assert require_tradeable(f"  {rating} ") == rating

    def test_review_is_never_substituted_with_hold_or_another_tier(self):
        for value in ("REVIEW", "review", "Strong Buy", ""):
            try:
                mapped = require_tradeable(value)
            except ValueError:
                continue
            pytest.fail(f"{value!r} was mapped to {mapped!r} instead of being refused")


# --- B. The gate's decision involves no LLM --------------------------------

@pytest.mark.unit
class TestGateIsDeterministicAndModelFree:
    def test_the_guard_imports_no_model_or_agent_component(self):
        assert _module_imports(GUARD_MODULE) & LLM_IMPORTS == set()

    def test_the_guard_imports_only_the_standard_library(self):
        assert _module_imports(GUARD_MODULE) == {"__future__", "dataclasses"}

    def test_the_guard_body_calls_no_model_invocation(self):
        """Static scan: no structured-output or invoke attribute is referenced."""
        source = GUARD_MODULE.read_text(encoding="utf-8")
        for forbidden in ("with_structured_output", ".invoke(", "structured_llm"):
            assert forbidden not in source

    @pytest.mark.parametrize("value", ["Buy", "REVIEW", "Strong Buy", None, ""])
    def test_the_same_input_always_gives_the_same_verdict(self, value):
        verdicts = {check_rating(value) for _ in range(5)}
        assert len(verdicts) == 1

    def test_the_verdict_carries_the_rule_version(self):
        for value in ("Buy", "REVIEW", "Strong Buy", None):
            assert check_rating(value).rule_version == GUARD_RULE_VERSION == "inv01-v1"
