from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from freeze.evidence_codec import encode_evidence
from freeze.issue import freeze_revision
from freeze.receive import receive_evidence
from handover.export import export_shift_reports
from handover.publish import sign_report
from handover.report_store import initialize_offline
from intake.import_records import record_batch
from intake.outcomes import Disposition, TrialRecord, WorkClass
from intake.source_store import initialize_source
from revision.amendments import amend_revision
from revision.count_audit import audit_revision


_SAMPLES = Path(__file__).resolve().parent / 'samples'


def _sample(name):
    return json.loads((_SAMPLES / name).read_text(encoding='utf-8'))


def run_demo(directory):
    intake = _sample('shift_records.json')
    correction = _sample('shift_correction.json')
    records = [TrialRecord(
        item['record_id'], item['source_ref'], WorkClass(item['work_class']), Disposition(**item['disposition']),
    ) for item in intake['records']]
    offline_path = directory / 'night.sqlite'
    with closing(sqlite3.connect(offline_path)) as offline_db:
        offline = initialize_offline(offline_db)
        with closing(sqlite3.connect(directory / 'source.sqlite')) as source_db:
            source = initialize_source(source_db)
            root = record_batch(source, intake['batch_id'], records)
            original = audit_revision(source, root.revision_id)
            _, corrected = amend_revision(
                source, original.revision_id, correction['record_id'], Disposition(**correction['disposition']),
            )
            issued = [freeze_revision(source, audit.revision_id) for audit in (original, corrected)]
            receipt_ids = [receive_evidence(offline.evidence, encode_evidence(item), item.provenance) for item in issued]
        report_ids = [sign_report(offline, receipt_id).report_id for receipt_id in receipt_ids]
    with closing(sqlite3.connect(offline_path)) as offline_db:
        rows = json.loads(export_shift_reports(initialize_offline(offline_db), report_ids))
    for row in rows:
        origin = row.pop('provenance')
        row['batch_id'] = origin['batch_id']
        row['revision_id'] = origin['revision_id']
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    with TemporaryDirectory(prefix='repair-shift-') as directory:
        run_demo(Path(directory))
