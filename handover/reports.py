from dataclasses import dataclass
from fractions import Fraction

from analysis.report_result import ReportResult
from analysis.review_work import ReviewExpectation, ReviewExpectationKind
from freeze.evidence import EvidenceProvenance
from handover.report_store import ReportStore
from ledger_sql import is_row_id


class ReportNotFound(LookupError):
    """No signed report exists under the requested number."""


@dataclass(frozen=True)
class SignedReport:
    report_id: int
    provenance: EvidenceProvenance
    result: ReportResult


def get_report(store: ReportStore, report_id) -> SignedReport:
    if not is_row_id(report_id):
        raise ReportNotFound(report_id)
    entry = store.read_report(report_id)
    if entry is None:
        raise ReportNotFound(report_id)
    value = None if entry.review_value is None else Fraction(entry.review_value)
    review = ReviewExpectation(ReviewExpectationKind(entry.review_kind), value)
    result = ReportResult(Fraction(entry.completion_probability), review)
    origin = EvidenceProvenance(entry.evidence_id, entry.source_id, entry.batch_id, entry.revision_id)
    return SignedReport(report_id, origin, result)
