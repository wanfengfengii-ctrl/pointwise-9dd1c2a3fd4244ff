from dataclasses import asdict
from fractions import Fraction
import json
import sqlite3

from handover.export import export_shift_reports
from handover.publish import sign_report
from handover.report_store import initialize_offline
from handover.reports import ReportNotFound, get_report
from handover.shift_queue import collect_shift_reports
from intake.outcomes import Disposition
from ledger_sql import StoreInitializationError
from revision.amendments import amend_revision
from revision.count_audit import audit_revision
from tests.support import LedgerCase, special_trial, trial


class TestHandover(LedgerCase):
    def _sign_two_revisions(self):
        root = self.root(trial('C1', review=True), special_trial('S1'))
        first = self.issue(root)
        first_receipt = self.receive(first)
        corrected, _ = amend_revision(self.source, root.revision_id, 'C1', Disposition(0, 0, False))
        second = self.issue(corrected)
        second_receipt = self.receive(second)
        self.source.db.close()
        first_report = sign_report(self.offline, first_receipt)
        second_report = sign_report(self.offline, second_receipt)
        self.assertEqual(first_report.provenance, first.provenance)
        self.assertEqual(second_report.provenance, second.provenance)
        return first_report, second_report

    def test_reissue(self):
        first, second = self._sign_two_revisions()
        self.assertNotEqual(first.report_id, second.report_id)
        self.assertNotEqual(first.provenance.revision_id, second.provenance.revision_id)
        self.reopen_offline()
        old = get_report(self.offline, first.report_id)
        new = get_report(self.offline, second.report_id)
        self.assertEqual((old, new), (first, second))
        self.assert_report(old, Fraction(1), Fraction(1))
        self.assert_report(new, Fraction(1), Fraction(0))

    def test_offline_export(self):
        first, second = self._sign_two_revisions()
        self.reopen_offline()
        connection = self.offline.db
        reads = []

        def deny_evidence_read(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_READ and arg1 == 'received_evidence':
                reads.append((arg1, arg2))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_evidence_read)
        try:
            ids = [second.report_id, first.report_id, second.report_id]
            reports = collect_shift_reports(self.offline, ids)
            self.assertEqual(reports, (second, first, second))
            rows = json.loads(export_shift_reports(self.offline, ids))
            self.assertEqual(export_shift_reports(self.offline, []), '[]')
            with self.assertRaises(ReportNotFound):
                export_shift_reports(self.offline, [first.report_id, second.report_id + 99])
        finally:
            connection.set_authorizer(None)
        self.assertEqual(reads, [])
        self.assertEqual([row['report_id'] for row in rows], ids)
        self.assertEqual([row['provenance'] for row in rows],
                         [asdict(second.provenance), asdict(first.provenance), asdict(second.provenance)])
        self.assertEqual([row['completion_probability'] for row in rows], ['1', '1', '1'])
        self.assertEqual([row['review'] for row in rows], [
            {'kind': 'finite', 'value': '0'}, {'kind': 'finite', 'value': '1'}, {'kind': 'finite', 'value': '0'},
        ])
        self.assertEqual((self.evidence_count(), self.report_count()), (2, 2))

    def test_offline_store_kind(self):
        root = self.root(trial('C1'), special_trial('S1'))
        original = audit_revision(self.source, root.revision_id)
        with self.assertRaises(StoreInitializationError):
            initialize_offline(self.source.db)
        self.assertEqual(audit_revision(self.source, root.revision_id), original)
        tables = self.source.db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'").fetchall()
        self.assertNotIn(('signed_reports',), tables)
