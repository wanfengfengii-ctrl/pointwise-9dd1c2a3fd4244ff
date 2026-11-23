"""Demo: the V1 shift flow, then mixture signing with source shutdown.

The mixture half freezes two V1 calibration items into an ordered handover
manifest, receives it offline, signs the interval verdict after the source
ledger is shut down, and reads the archived verdict back by its original
number after reopening the work ledger.
"""
from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from demo import run_demo
from freeze.evidence_codec import encode_evidence
from freeze.issue import freeze_mix
from freeze.receive import receive_mix
from handover.publish import sign_mix_report
from handover.report_store import initialize_offline
from handover.reports import get_mix_report
from intake.source_store import initialize_source
from mix_fixture import issue_pair


# (sample case, completion_min, review_max) for the [0, 1] window
_PLANNED = (
    ('interior-peak', 1, Fraction(7, 20)),
    ('critical', Fraction(1, 3), 2),
)


def _archived_row(case, report_id, record):
    passed, mix_id, parents, window, thresholds = record
    return {
        'case': case,
        'report_id': report_id,
        'passed': passed,
        'mix_id': mix_id,
        'left_evidence_id': parents[0].evidence_id,
        'right_evidence_id': parents[1].evidence_id,
        'left_batch_id': parents[0].batch_id,
        'right_batch_id': parents[1].batch_id,
        'low': str(window[0]),
        'high': str(window[1]),
        'completion_min': str(thresholds[0]),
        'review_max': str(thresholds[1]),
    }


def run_mix_demo(directory):
    offline_path = directory / 'mix-night.sqlite'
    with closing(sqlite3.connect(offline_path)) as offline_db:
        offline = initialize_offline(offline_db)
        with closing(sqlite3.connect(directory / 'mix-source.sqlite')) as source_db:
            source = initialize_source(source_db)
            handed_over = []
            for case, completion_min, review_max in _PLANNED:
                left, right = issue_pair(source, case)
                payloads = (encode_evidence(left), encode_evidence(right))
                mix_id, manifest = freeze_mix(payloads[0], payloads[1], 0, 1)
                handed_over.append((case, completion_min, review_max, mix_id, manifest, payloads))
        # The source ledger is shut down; the night shift works offline.
        signed = []
        for case, completion_min, review_max, mix_id, manifest, payloads in handed_over:
            receipt = receive_mix(offline, mix_id, manifest, payloads[0], payloads[1])
            report_id, passed = sign_mix_report(offline, receipt, completion_min, review_max)
            signed.append((case, report_id))
            print(json.dumps({
                'case': case, 'mix_id': receipt, 'report_id': report_id, 'passed': passed,
            }, sort_keys=True))
    # Reopen the work ledger and collect the archived verdicts by number.
    with closing(sqlite3.connect(offline_path)) as offline_db:
        offline = initialize_offline(offline_db)
        for case, report_id in signed:
            record = get_mix_report(offline, report_id)
            print(json.dumps(_archived_row(case, report_id, record), sort_keys=True))


if __name__ == '__main__':
    with TemporaryDirectory(prefix='repair-shift-') as directory:
        run_demo(Path(directory))
    with TemporaryDirectory(prefix='repair-mix-') as directory:
        run_mix_demo(Path(directory))
