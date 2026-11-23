from collections.abc import Iterable

from handover.report_store import ReportStore
from handover.reports import SignedReport, get_report


def collect_shift_reports(store: ReportStore, report_ids: Iterable[int]) -> tuple[SignedReport, ...]:
    """Retrieve the exact numbered reports in the supplied handover order."""
    return tuple(get_report(store, report_id) for report_id in report_ids)
