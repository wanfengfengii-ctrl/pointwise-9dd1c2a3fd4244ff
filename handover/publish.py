from fractions import Fraction
import sqlite3

from analysis.mixture import build_mixture_model, mixture_interval_passes
from analysis.report_result import compute_report_result
from freeze.receive import ReceiptRejected, load_received_evidence
from handover.report_store import MixReportEntry, ReportEntry, ReportStore
from handover.reports import SignedReport
from intake.record_checks import valid_name


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


def _threshold(value, allow_zero, label):
    if type(value) is bool or not isinstance(value, (int, Fraction)):
        raise ValueError(f'{label} must be an integer or fraction')
    threshold = Fraction(value)
    if allow_zero:
        valid = threshold >= 0
    else:
        valid = threshold > 0
    if not valid:
        raise ValueError(f'{label} must be a {"nonnegative" if allow_zero else "positive"} rational')
    return threshold


def sign_mix_report(store: ReportStore, mix_id, completion_min, review_max):
    """Sign the interval verdict for a received mixture; returns (report_id, passed)."""
    completion_min = _threshold(completion_min, False, 'completion_min')
    review_max = _threshold(review_max, True, 'review_max')
    if not valid_name(mix_id):
        raise ReportSigningFailed('invalid mixture receipt id')
    try:
        mixture = store.find_mixture(mix_id)
    except sqlite3.Error as exc:
        raise ReportSigningFailed('could not read the received mixture') from exc
    if mixture is None:
        raise ReportSigningFailed('no usable mixture for the requested report')
    try:
        left = load_received_evidence(store.evidence, mixture.left_id)
        right = load_received_evidence(store.evidence, mixture.right_id)
    except ReceiptRejected as exc:
        raise ReportSigningFailed('no usable evidence for the requested report') from exc
    model = build_mixture_model(left.rows, right.rows)
    passed = mixture_interval_passes(model, mixture.low, mixture.high, completion_min, review_max)
    entry = MixReportEntry(mix_id, int(passed), str(completion_min), str(review_max))
    try:
        report_id = store.commit_mix_report(entry)
    except sqlite3.Error as exc:
        raise ReportSigningFailed('could not commit the signed report') from exc
    return report_id, passed
