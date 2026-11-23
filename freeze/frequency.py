from collections import Counter
from dataclasses import dataclass
from fractions import Fraction

from intake.outcomes import Disposition, WorkClass
from intake.record_checks import validate_disposition
from revision.count_audit import AuditResult


@dataclass(frozen=True)
class JointFrequency:
    work_class: WorkClass
    disposition: Disposition
    count: int
    frequency: Fraction


def validate_joint_frequencies(rows):
    counts = Counter()
    masses = Counter()
    previous = None
    special_closures = 0
    for row in rows:
        validate_disposition(row.work_class, row.disposition)
        key = row.work_class, row.disposition
        if previous is not None and key <= previous:
            raise ValueError('joint rows must be unique and in canonical order')
        previous = key
        if type(row.count) is not int or row.count <= 0:
            raise ValueError('joint counts must be positive integers')
        if not isinstance(row.frequency, Fraction) or row.frequency <= 0:
            raise ValueError('joint frequencies must be positive rational values')
        counts[row.work_class] += row.count
        masses[row.work_class] += row.frequency
        if row.work_class is WorkClass.SPECIAL and row.disposition.special_children == 0:
            special_closures += row.count
    if any(counts[work_class] == 0 for work_class in WorkClass):
        raise ValueError('both work classes need disposition records')
    if special_closures == 0:
        raise ValueError('special work needs a positive closure frequency')
    if any(masses[work_class] != 1 for work_class in WorkClass):
        raise ValueError('frequencies must sum to one within each work class')
    for row in rows:
        if row.frequency != Fraction(row.count, counts[row.work_class]):
            raise ValueError('frequency does not agree with its joint count')


def build_joint_frequencies(audit: AuditResult) -> tuple[JointFrequency, ...]:
    totals = dict(audit.class_totals)
    if any(totals.get(work_class, 0) <= 0 for work_class in WorkClass):
        raise ValueError('both work classes need disposition records')
    rows = tuple(
        JointFrequency(row.work_class, row.disposition, row.count, Fraction(row.count, totals[row.work_class]))
        for row in audit.rows
    )
    validate_joint_frequencies(rows)
    actual_totals = Counter()
    for row in rows:
        actual_totals[row.work_class] += row.count
    if actual_totals != totals or sum(actual_totals.values()) != audit.total_records:
        raise ValueError('joint counts do not agree with the audited totals')
    return rows
