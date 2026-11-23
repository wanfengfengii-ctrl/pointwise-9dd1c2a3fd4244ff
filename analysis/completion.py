from dataclasses import dataclass
from fractions import Fraction

from analysis.offspring import OffspringDistribution


@dataclass(frozen=True)
class CompletionProbabilities:
    ordinary: Fraction
    special: Fraction


def compute_completion_probabilities(distribution: OffspringDistribution) -> CompletionProbabilities:
    # A special lineage ends almost surely because each attempt can close it.
    special = Fraction(1)
    zero, _, two = distribution.ordinary_count_probabilities()
    # With special extinction certain, the ordinary fixed-point polynomial
    # factors as (q - 1) * (two * q - zero). If no outcome ends the
    # ordinary lineage, zero is the least root, including pure single renewal.
    if zero == 0:
        ordinary = Fraction(0)
    elif two == 0:
        ordinary = Fraction(1)
    else:
        ordinary = min(Fraction(1), zero / two)
    return CompletionProbabilities(ordinary, special)
