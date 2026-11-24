"""INV-02: the decision's own size must be a percentage within the cap.

The cases below judge the *composed* verdict — INV-01's rating gate followed by
the sizing gate, i.e. what a caller would act on — rather than the parser's
float. A parser that reads "6%" from a summary that says "all in" somewhere is
not covered by a test that only asserts ``percent == 6.0``.

The decision text under test is built with the repository's own renderer where
that is possible, so the extraction is exercised against the format the
pipeline actually produces rather than a format invented here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating, render_pm_decision
from tradingagents.safety.guard import RATING_REVIEW, TRADEABLE_RATINGS
from tradingagents.safety.sizing import (
    MAX_POSITION_PCT,
    PASS,
    SIZING_RULE_VERSION,
    VETO_AMBIGUOUS,
    VETO_NO_SIZE,
    VETO_NO_SUMMARY,
    VETO_NOT_TEXT,
    VETO_OVER_CAP,
    VETO_UNPARSEABLE,
    apply_to_rating,
    check_position_size,
    executive_summary,
)

SIZING_MODULE = (
    Path(__file__).resolve().parents[2] / "src" / "tradingagents" / "safety" / "sizing.py"
)

# Imports that would let a model influence the verdict. ``tradingagents`` is
# allowed here, unlike in the INV-01 scan, because this gate composes with the
# INV-01 guard — but only the rating guard, which is itself model-free.
MODEL_IMPORTS = {
    "langchain", "langchain_core", "langchain_openai", "langchain_anthropic",
    "langgraph", "openai", "anthropic", "google", "transformers", "ollama",
}

SIZED = "the guard must accept this size and keep the tradeable rating"
REFUSED = "the guard must resolve this to REVIEW, whatever the rating"


def _module_imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def decision(summary: str, rating: PortfolioRating = PortfolioRating.BUY) -> str:
    """A decision rendered by the pipeline's own renderer."""
    return render_pm_decision(
        PortfolioDecision(
            rating=rating,
            executive_summary=summary,
            investment_thesis="Cloud backlog intact; 40% of revenue is contracted.",
        )
    )


def verdict(rating: object, summary: str):
    """The composed INV-01 + INV-02 verdict for a rendered decision."""
    return apply_to_rating(rating, decision(summary))


# --- A. The cap -----------------------------------------------------------

@pytest.mark.unit
class TestTheCapItself:
    def test_the_cap_is_ten_percent(self):
        assert MAX_POSITION_PCT == 10.0

    def test_exactly_at_the_cap_passes(self):
        result = verdict("Buy", "Initiate a 10% of portfolio position.")
        assert result.tradeable is True
        assert result.rating == "Buy"
        assert result.reason == PASS

    @pytest.mark.parametrize("summary", [
        "10 % of portfolio",
        "10.0% of the portfolio",
        "10% portfolio cap.",
    ])
    def test_the_cap_is_inclusive_however_it_is_written(self, summary):
        result = verdict("Buy", summary)
        assert result.tradeable is True
        assert result.rating == "Buy"

    @pytest.mark.parametrize("percent", [10.5, 11, 12, 25, 50, 80, 100, 150])
    def test_above_the_cap_is_review(self, percent):
        result = verdict("Buy", f"Allocate {percent}% of portfolio.")
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_OVER_CAP

    def test_the_requirement_fixture_12_percent_against_a_10_percent_cap_is_blocked(self):
        """INV-02's own fit criterion: '12% of portfolio' against a 10% cap."""
        result = verdict("Buy", "12% of portfolio")
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_OVER_CAP

    def test_the_requirement_fixture_80_percent_is_blocked(self):
        result = verdict("Buy", "80% of portfolio")
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_OVER_CAP


# --- B. Valid sizes below the cap -----------------------------------------

@pytest.mark.unit
class TestSizesBelowTheCapPass:
    @pytest.mark.parametrize("percent,summary", [
        (1, "Use a 1% of portfolio starter."),
        (3, "Maintain a 3% weight."),
        (5, "5% of portfolio"),
        (6, "Enter at $189-192, 6% portfolio cap."),
        (7.5, "Scale in to 7.5% of the book."),
        (9, "Build 9% exposure."),
        (10, "10% of portfolio"),
    ])
    def test_a_valid_size_keeps_the_tradeable_rating(self, percent, summary):
        result = verdict("Overweight", summary)
        assert result.tradeable is True
        assert result.rating == "Overweight"
        assert result.reason == PASS
        assert check_position_size(decision(summary)).percent == percent

    def test_a_valid_size_does_not_change_which_tradeable_rating_was_given(self):
        """The sizing gate judges the size; it does not re-decide the rating."""
        for rating in TRADEABLE_RATINGS:
            assert verdict(rating, "Buy a 5% of portfolio position.").rating == rating

    def test_the_passed_verdict_carries_the_inv02_rule_version(self):
        assert verdict("Buy", "5% of portfolio").rule_version == SIZING_RULE_VERSION

    def test_a_refused_size_exposes_no_percent_to_read(self):
        """A vetoed decision must not hand a caller a number to size from."""
        for summary in ("All in", "12% of portfolio", "5%-8% of portfolio"):
            assert check_position_size(decision(summary)).percent is None


# --- C. Missing size information ------------------------------------------

@pytest.mark.unit
class TestMissingInformationFailsClosed:
    def test_missing_executive_summary_is_review(self):
        text = "**Rating**: Buy\n\n**Investment Thesis**: AI capex cycle intact."
        result = apply_to_rating("Buy", text)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_NO_SUMMARY

    def test_an_empty_executive_summary_is_review(self):
        result = verdict("Buy", "")
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_NO_SIZE

    @pytest.mark.parametrize("summary", [
        "No position sizing specified.",
        "Take a small starter and add on confirmation.",
        "Initiate a full position.",
        "Build the position in three tranches.",
        "Half in now, half on the next print.",
        "Size it proportionally to conviction.",
    ])
    def test_a_summary_without_a_stated_size_is_review(self, summary):
        result = verdict("Buy", summary)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_NO_SIZE

    @pytest.mark.parametrize("text", [None, "", "Buy the dip.", 5, 3.14, True, [], {}, object()])
    def test_a_decision_with_no_readable_text_is_review(self, text):
        result = apply_to_rating("Buy", text)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason in {VETO_NO_SUMMARY, VETO_NOT_TEXT}

    def test_missing_size_is_never_read_as_zero_exposure(self):
        """A refused size must not become a "hold nothing" position.

        The verdict is REVIEW, and REVIEW is not a position; it is not a pass
        carrying 0% either.
        """
        result = verdict("Buy", "No position sizing specified.")
        assert result.passed is False
        assert result.rating == RATING_REVIEW
        assert check_position_size(decision("No position sizing specified.")).percent is None

    def test_an_explicit_zero_is_not_a_size_the_guard_endorses(self):
        result = verdict("Buy", "Hold a 0% of portfolio position.")
        assert result.tradeable is False
        assert result.reason == VETO_UNPARSEABLE


# --- D. Unparseable and unsupported expressions ---------------------------

@pytest.mark.unit
class TestUnparseableSizesAreReview:
    @pytest.mark.parametrize("summary", [
        "All in.",
        "Go all-in on this one.",
        "1.5x leverage",
        "Use 2x leverage on the position.",
        "Leverage up the portfolio.",
    ])
    def test_the_requirement_fixtures_all_in_and_1_5x_leverage_are_blocked(self, summary):
        result = verdict("Buy", summary)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_UNPARSEABLE

    @pytest.mark.parametrize("summary", [
        "Take a 6% of the portfolio position, using leverage.",
        "Size the position at 5% and lever it.",
    ])
    def test_a_percentage_alongside_leverage_is_still_blocked(self, summary):
        """A valid-looking percentage must not launder an unsupported structure."""
        result = verdict("Buy", summary)
        assert result.rating == RATING_REVIEW

    @pytest.mark.parametrize("summary", [
        "Use 6 percent of the portfolio.",
        "Commit five percent of the portfolio.",
        "Put a fraction of the portfolio to work.",
    ])
    def test_a_size_not_written_as_a_percentage_is_review(self, summary):
        assert verdict("Buy", summary).rating == RATING_REVIEW


# --- E. Ambiguity and conflict --------------------------------------------

@pytest.mark.unit
class TestAmbiguousOrConflictingSizesAreReview:
    @pytest.mark.parametrize("summary", [
        "Use 5%-8% of portfolio.",
        "Use 5–8% of portfolio.",
        "Use 5 to 8% of portfolio.",
        "Take a 4% to 12% allocation.",
    ])
    def test_a_range_is_not_a_single_size(self, summary):
        result = verdict("Buy", summary)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_AMBIGUOUS

    @pytest.mark.parametrize("summary", [
        "Buy 5% of the portfolio, scaling to 12% on strength.",
        "Buy 5% of the portfolio. Add another 8% on the breakout.",
        "Trim the 12% position to 5% of the portfolio.",
        "Start at 3% of the portfolio; go to 9% on confirmation.",
    ])
    def test_two_conflicting_sizes_are_review(self, summary):
        """Even when *both* are within the cap, the stated size is not one size."""
        result = verdict("Buy", summary)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        # The reason must be ambiguity, not a parse failure that happens to veto.
        assert result.reason == VETO_AMBIGUOUS

    @pytest.mark.parametrize("summary", [
        "Enter 6% of portfolio, 3% stop.",
        "Use 5% of portfolio with a 2% stop.",
    ])
    def test_a_position_percentage_beside_a_stop_distance_is_review(self, summary):
        """'6% of portfolio, 3% stop': the summary does not say which is the size.

        The guard cannot tell a size percentage from a risk percentage when both
        follow one number-less clause, so it refuses rather than picks the first.
        """
        result = verdict("Buy", summary)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason == VETO_AMBIGUOUS

    @pytest.mark.parametrize("summary", [
        "Buy 5% of the portfolio; stop at 3% loss.",
        "Enter 5% of the portfolio, then exit if it falls 3%.",
        "Hold 5% of the portfolio; trim to 3% if it breaks support.",
        "Enter 6% of portfolio and stop 3% below entry.",
    ])
    def test_an_exit_clause_after_a_clear_size_does_not_make_it_ambiguous(self, summary):
        """A later exit/stop verb says the trailing number is the loss, not the size.

        This is the ordinary "5% position, 3% stop" shape: the size comes before
        the risk instruction, so it is read as the size.
        """
        result = verdict("Buy", summary)
        assert result.tradeable is True
        assert result.rating == "Buy"
        assert check_position_size(decision(summary)).percent == (5.0 if "5%" in summary else 6.0)


# --- F. Percentages outside the Executive Summary -------------------------

@pytest.mark.unit
class TestOnlyTheExecutiveSummaryIsRead:
    def test_a_size_only_in_the_thesis_does_not_rescue_a_sizeless_summary(self):
        text = (
            "**Rating**: Buy\n\n"
            "**Executive Summary**: Initiate a position and review at earnings.\n\n"
            "**Investment Thesis**: The trader sized this at 40% of the portfolio."
        )
        result = apply_to_rating("Buy", text)
        assert result.tradeable is False
        assert result.reason == VETO_NO_SIZE

    def test_a_size_only_before_the_summary_is_not_read(self):
        text = (
            "Trader proposal: **Position Sizing**: 4% of portfolio\n\n"
            + decision("Buy the position now.")
        )
        result = apply_to_rating("Buy", text)
        assert result.tradeable is False
        assert result.reason == VETO_NO_SIZE
        assert "4%" not in (executive_summary(text) or "")

    def test_an_over_cap_percentage_elsewhere_does_not_veto_a_valid_summary(self):
        result = verdict(
            "Buy",
            "Buy 5% of the portfolio.",
        )
        assert result.tradeable is True
        # The thesis carries "40% of revenue": not a size, and not read as one.
        assert "40%" in decision("Buy 5% of the portfolio.")

    def test_the_traders_position_sizing_is_not_used_as_a_substitute(self):
        """INV-02 guards the decision's own size, not the trader's input to it."""
        text = (
            "**Position Sizing**: 5% of portfolio\n\n"
            + decision("All in.")
        )
        result = apply_to_rating("Buy", text)
        assert result.tradeable is False
        assert result.reason == VETO_UNPARSEABLE

    def test_the_summary_span_ends_at_the_next_section(self):
        text = decision("Use 4% of the portfolio.") + "\n\n**Notes**: 90% of portfolio."
        assert executive_summary(text) == "Use 4% of the portfolio."

    def test_percentages_within_the_summary_that_do_not_size_the_position_are_ignored(self):
        """An upside target in the summary is not the position's size."""
        result = verdict("Buy", "Buy 5% of the portfolio. Target 15% upside.")
        assert result.tradeable is True
        assert result.rating == "Buy"

    def test_a_stop_loss_in_the_summary_does_not_override_the_size(self):
        result = verdict("Buy", "Buy 5% of the portfolio; stop at 3% loss.")
        assert result.tradeable is True
        assert check_position_size(decision("Buy 5% of the portfolio; stop at 3% loss.")).percent == 5.0


# --- G. INV-01 precedence -------------------------------------------------

@pytest.mark.unit
class TestInv01PrecedenceIsPreserved:
    @pytest.mark.parametrize("summary", [
        "5% of portfolio",
        "10% of portfolio",
        "12% of portfolio",
        "All in",
        "No position sizing specified.",
    ])
    def test_a_valid_size_never_lifts_an_inv01_review(self, summary):
        """The clause in INV-02: a valid size must not turn REVIEW tradeable."""
        result = verdict(RATING_REVIEW, summary)
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW
        assert result.reason == "review_not_tradeable"

    def test_an_inv01_review_keeps_its_inv01_reason(self):
        """The final verdict keeps INV-01's reason when INV-01 is what vetoed.

        The comment on the composition says INV-01 and INV-02 vetoes stay
        distinguishable in a log; the reason holds that, but ``rule_version``
        does not (see the report's limitations — it needs a merge decision).
        """
        result = verdict(RATING_REVIEW, "5% of portfolio")
        assert result.reason == "review_not_tradeable"

    @pytest.mark.parametrize("rating", ["Strong Buy", "overweight plus", "", None, 42])
    def test_an_inv01_out_of_enum_rating_is_not_lifted_by_a_valid_size(self, rating):
        result = verdict(rating, "5% of portfolio")
        assert result.tradeable is False
        assert result.rating == RATING_REVIEW

    @pytest.mark.parametrize("rating", TRADEABLE_RATINGS)
    @pytest.mark.parametrize("summary,expected_reason", [
        ("5% of portfolio", PASS),
        ("80% of portfolio", VETO_OVER_CAP),
        ("All in", VETO_UNPARSEABLE),
        ("5%-8% of portfolio", VETO_AMBIGUOUS),
        ("", VETO_NO_SIZE),
    ])
    def test_an_invalid_size_forces_review_on_every_tradeable_rating(
        self, rating, summary, expected_reason
    ):
        result = verdict(rating, summary)
        if expected_reason == PASS:
            assert result.tradeable is True
            assert result.rating == rating
        else:
            assert result.tradeable is False
            assert result.rating == RATING_REVIEW
            assert result.reason == expected_reason


# --- H. The gate is deterministic and model-free --------------------------

@pytest.mark.unit
class TestGateIsDeterministicAndModelFree:
    def test_the_guard_imports_no_model_component(self):
        assert _module_imports(SIZING_MODULE) & MODEL_IMPORTS == set()

    def test_the_guard_imports_only_the_standard_library_and_the_rating_guard(self):
        assert _module_imports(SIZING_MODULE) == {
            "__future__", "re", "dataclasses", "tradingagents",
        }

    def test_the_guard_imports_no_agent_or_graph_component(self):
        """No agent node, state, or graph wiring: the gate reads text, not the run."""
        source = SIZING_MODULE.read_text(encoding="utf-8")
        for forbidden in (
            "tradingagents.agents", "tradingagents.graph", "AgentState",
            "portfolio_manager", "with_structured_output", ".invoke(", "structured_llm",
        ):
            assert forbidden not in source

    @pytest.mark.parametrize("summary", [
        "5% of portfolio", "12% of portfolio", "All in", "5%-8% of portfolio", "",
    ])
    def test_the_same_input_always_gives_the_same_verdict(self, summary):
        results = {verdict("Buy", summary) for _ in range(5)}
        assert len(results) == 1

    @pytest.mark.parametrize("text", [
        "**Rating**: Buy\n\n**Executive Summary**: 5% of portfolio\n",
        "**Rating**: Buy\n\n**Executive Summary**: 40% of portfolio\n",
    ])
    def test_the_same_decision_text_always_gives_the_same_verdict(self, text):
        assert len({apply_to_rating("Buy", text) for _ in range(5)}) == 1
