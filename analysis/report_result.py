from dataclasses import dataclass
from fractions import Fraction

from analysis.completion import compute_completion_probabilities
from analysis.offspring import build_offspring_distribution
from analysis.review_work import ReviewExpectation, ReviewExpectationKind, conditional_review_expectation
from freeze.evidence import FrozenEvidence


@dataclass(frozen=True)
class ReportResult:
    completion_probability: Fraction
    review: ReviewExpectation

    def __post_init__(self):
        probability = self.completion_probability
        if not isinstance(probability, Fraction) or not 0 <= probability <= 1:
            raise ValueError('completion probability must be a fraction between zero and one')
        if (probability == 0) != (self.review.kind is ReviewExpectationKind.NOT_APPLICABLE):
            raise ValueError('completion probability and review expectation disagree')


def compute_report_result(evidence: FrozenEvidence) -> ReportResult:
    distribution = build_offspring_distribution(evidence.rows)
    completion = compute_completion_probabilities(distribution)
    review = conditional_review_expectation(distribution, completion)
    return ReportResult(completion.ordinary, review)
