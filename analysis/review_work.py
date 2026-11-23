from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from analysis.completion import CompletionProbabilities
from analysis.offspring import OffspringDistribution


class ReviewExpectationKind(StrEnum):
    NOT_APPLICABLE = 'not_applicable'
    FINITE = 'finite'
    INFINITE = 'infinite'


@dataclass(frozen=True)
class ReviewExpectation:
    kind: ReviewExpectationKind
    value: Fraction | None = None

    def __post_init__(self):
        if not isinstance(self.kind, ReviewExpectationKind):
            raise ValueError('unknown review expectation kind')
        if self.kind is ReviewExpectationKind.FINITE:
            if not isinstance(self.value, Fraction) or self.value < 0:
                raise ValueError('finite review work requires a nonnegative fraction')
        elif self.value is not None:
            raise ValueError('this review expectation cannot carry a finite value')


def _special_review_work(distribution: OffspringDistribution) -> Fraction:
    close = sum((event.probability for event in distribution.special if event.special_children == 0), Fraction(0))
    review = sum((event.probability for event in distribution.special if event.review), Fraction(0))
    return review / close


def conditional_review_expectation(distribution: OffspringDistribution,
                                   completion: CompletionProbabilities) -> ReviewExpectation:
    if completion.ordinary == 0:
        return ReviewExpectation(ReviewExpectationKind.NOT_APPLICABLE)
    ordinary_mean = Fraction(0)
    review_per_ordinary = Fraction(0)
    special_review = _special_review_work(distribution)
    for event in distribution.ordinary:
        # Conditioning qualifies a disposition only when all of its children close.
        children_close = completion.ordinary ** event.ordinary_children * completion.special ** event.special_children
        weight = event.probability * children_close / completion.ordinary
        ordinary_mean += weight * event.ordinary_children
        review_per_ordinary += weight * (int(event.review) + event.special_children * special_review)
    # Each successive ordinary generation contributes the same per-item work
    # times its expected size. At mean one the sum diverges only for positive work.
    if review_per_ordinary == 0:
        return ReviewExpectation(ReviewExpectationKind.FINITE, Fraction(0))
    if ordinary_mean == 1:
        return ReviewExpectation(ReviewExpectationKind.INFINITE)
    return ReviewExpectation(ReviewExpectationKind.FINITE, review_per_ordinary / (1 - ordinary_mean))
