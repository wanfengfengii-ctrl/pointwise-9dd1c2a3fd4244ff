from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

from freeze.frequency import JointFrequency
from intake.outcomes import WorkClass


@dataclass(frozen=True)
class OffspringEvent:
    ordinary_children: int
    special_children: int
    review: bool
    probability: Fraction


@dataclass(frozen=True)
class OffspringDistribution:
    ordinary: tuple[OffspringEvent, ...]
    special: tuple[OffspringEvent, ...]

    def ordinary_count_probabilities(self) -> tuple[Fraction, Fraction, Fraction]:
        zero = one = two = Fraction(0)
        for event in self.ordinary:
            if event.ordinary_children == 0:
                zero += event.probability
            elif event.ordinary_children == 1:
                one += event.probability
            else:
                two += event.probability
        return zero, one, two


def build_offspring_distribution(rows: Iterable[JointFrequency]) -> OffspringDistribution:
    groups = {work_class: [] for work_class in WorkClass}
    for row in rows:
        disposition = row.disposition
        groups[row.work_class].append(OffspringEvent(
            disposition.ordinary_children, disposition.special_children, disposition.review, row.frequency,
        ))
    return OffspringDistribution(tuple(groups[WorkClass.ORDINARY]), tuple(groups[WorkClass.SPECIAL]))
