from dataclasses import asdict
import json

from handover.reports import SignedReport
from handover.shift_queue import collect_shift_reports


def _export_row(report: SignedReport):
    review = report.result.review
    return {
        'report_id': report.report_id,
        'provenance': asdict(report.provenance),
        'completion_probability': str(report.result.completion_probability),
        'review': {'kind': review.kind.value, 'value': None if review.value is None else str(review.value)},
    }


def export_shift_reports(store, report_ids) -> str:
    rows = [_export_row(report) for report in collect_shift_reports(store, report_ids)]
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
