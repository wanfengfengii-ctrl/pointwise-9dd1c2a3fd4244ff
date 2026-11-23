from collections import Counter
from dataclasses import dataclass

from intake.outcomes import Disposition, WorkClass
from revision.selection import SelectedSample, select_revision_sample


@dataclass(frozen=True)
class JointCount:
    work_class: WorkClass
    disposition: Disposition
    count: int


@dataclass(frozen=True)
class AuditResult:
    source_id: str
    batch_id: str
    revision_id: int
    parent_id: int | None
    rows: tuple[JointCount, ...]
    class_totals: tuple[tuple[WorkClass, int], ...]
    total_records: int


def count_selected_sample(sample: SelectedSample) -> AuditResult:
    counts = Counter((record.work_class, record.disposition) for record in sample.records)
    rows = tuple(JointCount(work_class, disposition, count)
                 for (work_class, disposition), count in sorted(counts.items()))
    totals = Counter()
    for row in rows:
        totals[row.work_class] += row.count
    selected = sample.revision
    return AuditResult(
        sample.source_id, selected.batch_id, selected.revision_id, selected.parent_id, rows,
        tuple((work_class, totals[work_class]) for work_class in WorkClass), len(sample.records),
    )


def audit_revision(source, revision_id) -> AuditResult:
    return count_selected_sample(select_revision_sample(source, revision_id))
