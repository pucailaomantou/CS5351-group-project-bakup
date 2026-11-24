"""Deterministic safety boundary (workstream D).

Plain code that decides whether a decision may leave the pipeline. Nothing here
calls a model: a guard whose verdict a model could influence is not a boundary.
"""

from tradingagents.safety.guard import (
    CANONICAL_RATINGS,
    GUARD_RULE_VERSION,
    RATING_REVIEW,
    GuardVerdict,
    check_rating,
    require_tradeable,
)

__all__ = [
    "CANONICAL_RATINGS",
    "GUARD_RULE_VERSION",
    "RATING_REVIEW",
    "GuardVerdict",
    "check_rating",
    "require_tradeable",
]
