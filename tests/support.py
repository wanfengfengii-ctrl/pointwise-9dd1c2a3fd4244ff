from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from analysis.review_work import ReviewExpectationKind
from freeze.evidence_codec import encode_evidence
from freeze.issue import freeze_revision
from freeze.receive import receive_evidence
from handover.report_store import initialize_offline
from intake.import_records import record_batch
from intake.outcomes import Disposition, TrialRecord, WorkClass
from intake.source_store import initialize_source


def trial(record_id, ordinary=0, special=0, review=False, kind=WorkClass.ORDINARY):
    return TrialRecord(record_id, f'bench/{record_id}', kind, Disposition(ordinary, special, review))


def special_trial(record_id, successors=0, review=False):
    return trial(record_id, special=successors, review=review, kind=WorkClass.SPECIAL)


class LedgerCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='repair-ledger-tests-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source_path = self.directory / 'source.sqlite'
        self.offline_path = self.directory / 'offline.sqlite'
        self.source = initialize_source(self.connect(self.source_path))
        self.offline = initialize_offline(self.connect(self.offline_path))

    def connect(self, path):
        # Disable statement caching so authorization checks apply at each SQL boundary.
        connection = sqlite3.connect(path, cached_statements=0)
        self.addCleanup(connection.close)
        return connection

    def root(self, *records, batch='B01'):
        return record_batch(self.source, batch, records)

    def issue(self, revision):
        return freeze_revision(self.source, revision.revision_id)

    def receive(self, evidence):
        return receive_evidence(self.offline.evidence, encode_evidence(evidence), evidence.provenance)

    def reopen_offline(self):
        self.offline.db.close()
        self.offline = initialize_offline(self.connect(self.offline_path))

    def evidence_count(self):
        return self.offline.db.execute('SELECT count(*) FROM received_evidence').fetchone()[0]

    def report_count(self):
        return self.offline.db.execute('SELECT count(*) FROM signed_reports').fetchone()[0]

    def assert_report(self, report, probability, value, kind=ReviewExpectationKind.FINITE):
        self.assertEqual(report.result.completion_probability, probability)
        self.assertEqual(report.result.review.kind, kind)
        self.assertEqual(report.result.review.value, value)
