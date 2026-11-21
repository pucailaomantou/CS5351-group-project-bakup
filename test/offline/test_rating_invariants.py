"""INV-01: an unreadable rating resolves to REVIEW, never a tradeable one.

``parse_rating`` must return the REVIEW sentinel for anything it cannot read as
one of the five tiers. The danger this guards against is degrading to a
tradeable default (e.g. Hold): the next run is then told a decision was made
that nobody made (#1170). These cases are the ones named in the INV-01 fit
criterion plus their out-of-enum neighbours.

This tests the existing ``rating.py`` logic and is expected to pass; the guard
and position-mapper half of INV-01 (REVIEW must not become a position) is
test-first elsewhere, since that code is not implemented yet.
"""

import pytest

from tradingagents.agents.rating import is_review, parse_rating


@pytest.mark.unit
@pytest.mark.parametrize("text", [
    "Strong Buy",          # out-of-enum rating
    "overweight plus",     # out-of-enum rating
    "",                    # empty decision
])
def test_unreadable_rating_resolves_to_review(text):
    assert parse_rating(text) == "REVIEW"


@pytest.mark.unit
def test_a_valid_rating_is_returned_unchanged():
    """A genuine labelled in-enum rating is a real call and parses to itself."""
    assert parse_rating("Rating: Buy") == "Buy"


@pytest.mark.unit
@pytest.mark.parametrize("text", ["Strong Buy", "overweight plus", ""])
def test_review_is_not_tradeable(text):
    assert is_review(parse_rating(text)) is True


@pytest.mark.unit
@pytest.mark.parametrize("text, expected", [
    ("Rating: Buy", "Buy"),
    ("Rating: Overweight", "Overweight"),
    ("Rating: Hold", "Hold"),
    ("Rating: Underweight", "Underweight"),
    ("Rating: Sell", "Sell"),
])
def test_a_readable_rating_is_not_review(text, expected):
    """Control: a genuine in-enum rating still parses and is tradeable."""
    rating = parse_rating(text)
    assert rating == expected
    assert is_review(rating) is False
