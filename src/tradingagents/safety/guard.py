"""INV-01: the final rating must be one of six values, and REVIEW is not a position.

The boundary is deliberately independent of the upstream readers. ``parse_rating``
and ``is_review`` shape what the pipeline produces; this module decides whether
that value may be *acted on*. A value that reached ``final_rating`` by any route
— a model, a fallback, an initialised state, a future code change, a caller
assigning it directly — is judged on its own merits here, never trusted because
it is non-empty.

The decision is ordinary deterministic code: no model call, no structured-output
invocation, no AI self-check. This module imports nothing but the standard
library, so that is a structural property rather than a promise (see the import
scan in ``test/offline/test_inv01_guard.py``).

Fail-closed has one meaning here — the only way to pass is to be an exact
canonical tradeable rating after whitespace normalisation. Every other input,
including types this function was never meant to see, resolves to REVIEW.
"""

from __future__ import annotations

from dataclasses import dataclass

# The five tradeable tiers, most bullish to most bearish. Order is part of the
# published scale and matches ``agents.rating.RATINGS_5_TIER``.
TRADEABLE_RATINGS: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

# The non-tradeable sentinel. It is a valid *decision* — it says the decision was
# unusable — but never a position.
RATING_REVIEW = "REVIEW"

# Every value ``final_rating`` may hold (INV-01). Spelled out rather than
# derived from ``TRADEABLE_RATINGS`` so the permitted set is visible at a glance
# and cannot widen by accident when the tier list changes elsewhere.
CANONICAL_RATINGS: frozenset[str] = frozenset(TRADEABLE_RATINGS) | {RATING_REVIEW}

# The gate's rule identity, for GOV-01 provenance. Bump the suffix only when the
# rule below changes meaning; a decision records which rule judged it.
GUARD_RULE_VERSION = "inv01-v1"

# Reasons are stable identifiers, not prose, so a log or a test can match them.
PASS = "canonical_rating"
VETO_REVIEW = "review_not_tradeable"
VETO_OUT_OF_ENUM = "out_of_enum"
VETO_MISSING = "missing_or_empty"


@dataclass(frozen=True)
class GuardVerdict:
    """The gate's decision and why it made it.

    ``passed`` is the single thing a caller may act on. ``rating`` is the value
    to publish: the normalised rating when passed, REVIEW otherwise. ``reason``
    is one of the module's stable identifiers. ``rule_version`` records which
    rule judged the value (GOV-01).
    """

    passed: bool
    rating: str
    reason: str
    rule_version: str = GUARD_RULE_VERSION

    @property
    def tradeable(self) -> bool:
        """Whether this verdict may become a position. REVIEW never may."""
        return self.passed and self.rating != RATING_REVIEW


def _normalise(value: object) -> str | None:
    """Strip surrounding whitespace from a string; ``None`` for anything else.

    Any non-string (``None``, a number, a model object) is not a rating, so it
    is reported the same as an empty string rather than coerced with ``str()``:
    coercing would let ``None`` become the literal ``"None"`` and invent a value.
    """
    if not isinstance(value, str):
        return None
    return value.strip()


def check_rating(value: object) -> GuardVerdict:
    """Decide whether ``value`` may be published as ``final_rating``.

    Passes only an exact canonical tradeable rating (after whitespace stripping).
    REVIEW is recognised in any case and any surrounding whitespace and is
    vetoed as non-tradeable. Everything else — out-of-enum, missing, empty, or
    the wrong type — fails closed to REVIEW.

    Casing of tradeable ratings is exact: ``"buy"`` is not ``"Buy"``. Accepting
    case variants would silently widen the enum, and the published pipeline
    emits canonical casing (``decision.rating.value``).
    """
    rating = _normalise(value)
    if rating is None or not rating:
        return GuardVerdict(passed=False, rating=RATING_REVIEW, reason=VETO_MISSING)
    if rating.upper() == RATING_REVIEW:
        return GuardVerdict(passed=False, rating=RATING_REVIEW, reason=VETO_REVIEW)
    if rating in TRADEABLE_RATINGS:
        return GuardVerdict(passed=True, rating=rating, reason=PASS)
    return GuardVerdict(passed=False, rating=RATING_REVIEW, reason=VETO_OUT_OF_ENUM)


def require_tradeable(value: object) -> str:
    """Return the rating to act on, or refuse.

    For the point where a rating would become a position or an action: a
    canonical tradeable rating is returned normalised, and REVIEW (in any
    spelling) is refused with ``ValueError``. Nothing is ever substituted —
    no Hold, no nearest tier — so a caller cannot turn an unusable decision
    into a position by catching and defaulting.

    The repository has no position mapper today; this function is the boundary
    such a mapper must call, not a substitute for one.
    """
    verdict = check_rating(value)
    if not verdict.tradeable:
        raise ValueError(f"rating {value!r} is not tradeable: {verdict.reason}")
    return verdict.rating
