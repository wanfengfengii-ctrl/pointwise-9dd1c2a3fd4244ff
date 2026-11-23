import sqlite3

from analysis.report_result import compute_report_result
from freeze.receive import ReceiptRejected, load_received_evidence
from handover.report_store import ReportEntry, ReportStore
from handover.reports import SignedReport


class ReportSigningFailed(RuntimeError):
    """The requested report could not be signed and committed."""


def sign_report(store: ReportStore, evidence_id: str) -> SignedReport:
    try:
        evidence = load_received_evidence(store.evidence, evidence_id)
    except ReceiptRejected as exc:
        raise ReportSigningFailed('no usable evidence for the requested report') from exc
    result = compute_report_result(evidence)
    origin = evidence.provenance
    value = result.review.value
    entry = ReportEntry(
        str(result.completion_probability), result.review.kind.value,
        None if value is None else str(value),
        origin.evidence_id, origin.source_id, origin.batch_id, origin.revision_id,
    )
    try:
        report_id = store.commit_report(entry)
    except sqlite3.Error as exc:
        raise ReportSigningFailed('could not commit the signed report') from exc
    return SignedReport(report_id, origin, result)
