from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
import sqlite3

from analysis.review_work import ReviewExpectationKind
from freeze.evidence_codec import encode_evidence
from freeze.issue import IssuanceRejected, freeze_revision
from freeze.receive import ReceiptRejected, receive_evidence
from handover.publish import ReportSigningFailed, sign_report
from handover.reports import ReportNotFound, get_report
from intake.outcomes import Disposition, WorkClass
from revision.amendments import amend_revision
from revision.count_audit import audit_revision
from tests.support import LedgerCase, special_trial, trial


def _marginals(rows):
    offspring = Counter()
    reviews = Counter()
    for row in rows:
        event = row.disposition
        offspring[row.work_class, event.ordinary_children, event.special_children] += row.frequency
        reviews[row.work_class, event.review] += row.frequency
    return offspring, reviews


def _canonical(item):
    return json.dumps(item, sort_keys=True, separators=(',', ':')).encode('ascii')


class TestReports(LedgerCase):
    def _ordinary_piece(self):
        return self.issue(self.root(trial('C1', review=True), special_trial('S1')))

    def _branching_root(self):
        return self.root(
            trial('C1', review=True), trial('C2', ordinary=2), trial('C3', ordinary=2),
            trial('C4', ordinary=2), special_trial('S1'),
        )

    def test_offline_ordinary(self):
        evidence = self._ordinary_piece()
        receipt = self.receive(evidence)
        self.assertEqual(self.receive(evidence), receipt)
        self.assertEqual(self.evidence_count(), 1)
        self.source.db.close()
        signed = sign_report(self.offline, receipt)
        self.assert_report(signed, Fraction(1), Fraction(1))
        self.assertEqual(signed.provenance, evidence.provenance)
        self.assertEqual(get_report(self.offline, signed.report_id), signed)

    def test_issue_boundaries(self):
        only_ordinary = self.root(trial('C1'), batch='ONLY-C')
        only_special = self.root(special_trial('S1'), batch='ONLY-S')
        no_special_closure = self.root(trial('C2'), special_trial('S2', successors=1), batch='NO-STOP')
        self.assertEqual(dict(audit_revision(self.source, only_ordinary.revision_id).class_totals),
                         {WorkClass.ORDINARY: 1, WorkClass.SPECIAL: 0})
        for revision_id in (9999, only_ordinary.revision_id, only_special.revision_id, no_special_closure.revision_id):
            with self.subTest(revision_id=revision_id), self.assertRaises(IssuanceRejected):
                freeze_revision(self.source, revision_id)
        self.assertEqual(self.evidence_count(), 0)

    def test_special_rollup(self):
        root = self.root(trial('C1', special=1, review=True), special_trial('S1'),
                         special_trial('S2', successors=1, review=True))
        evidence = self.issue(root)
        receipt = self.receive(evidence)
        self.source.db.close()
        signed = sign_report(self.offline, receipt)
        self.assert_report(signed, Fraction(1), Fraction(2))
        self.assertEqual(signed.provenance, evidence.provenance)

    def test_invalid_evidence(self):
        evidence = self._ordinary_piece()
        envelope = json.loads(encode_evidence(evidence))
        envelope['body']['rows'][0]['count'] += 1
        with self.assertRaises(ReceiptRejected):
            receive_evidence(self.offline.evidence, _canonical(envelope), evidence.provenance)
        with self.assertRaises(ReceiptRejected):
            receive_evidence(self.offline.evidence, b'', evidence.provenance)
        with self.assertRaises(ReportSigningFailed):
            sign_report(self.offline, evidence.provenance.evidence_id)
        self.assertEqual((self.evidence_count(), self.report_count()), (0, 0))

    def test_invalid_joint_data_with_matching_digest(self):
        evidence = self.issue(self.root(trial('C1'), trial('C2', ordinary=1), special_trial('S1')))
        envelope = json.loads(encode_evidence(evidence))
        rows = envelope['body']['rows']
        rows[0]['frequency'] = '1/4'
        rows[1]['frequency'] = '3/4'
        digest = sha256(_canonical(envelope['body'])).hexdigest()
        envelope['id'] = digest
        origin = type(evidence.provenance)(digest, evidence.provenance.source_id, 'B01', evidence.provenance.revision_id)
        with self.assertRaisesRegex(ReceiptRejected, 'does not agree with its joint count'):
            receive_evidence(self.offline.evidence, _canonical(envelope), origin)
        self.assertEqual(self.evidence_count(), 0)

    def test_provenance_binding(self):
        root = self.root(trial('C1', review=True), trial('C2'), special_trial('S1'))
        intermediate, _ = amend_revision(self.source, root.revision_id, 'C1', Disposition(0, 0, False))
        corrected, _ = amend_revision(self.source, intermediate.revision_id, 'C2', Disposition(0, 0, True))
        first, second = self.issue(root), self.issue(corrected)
        self.assertEqual(first.rows, second.rows)
        self.assertNotEqual(first.provenance.evidence_id, second.provenance.evidence_id)
        self.source.db.close()
        for item, wrong in ((first, second), (second, first)):
            with self.assertRaises(ReceiptRejected):
                receive_evidence(self.offline.evidence, encode_evidence(item), wrong.provenance)
            with self.assertRaises(ReportSigningFailed):
                sign_report(self.offline, item.provenance.evidence_id)
        self.assertEqual((self.evidence_count(), self.report_count()), (0, 0))
        valid = self.receive(first)
        self.assertEqual(sign_report(self.offline, valid).provenance, first.provenance)

    def _assert_never_closes(self, children):
        evidence = self.issue(self.root(trial('C1', ordinary=children, review=True), special_trial('S1')))
        receipt = self.receive(evidence)
        self.source.db.close()
        signed = sign_report(self.offline, receipt)
        self.assert_report(signed, Fraction(0), None, ReviewExpectationKind.NOT_APPLICABLE)
        self.assertEqual(get_report(self.offline, signed.report_id), signed)

    def test_no_completion(self):
        self._assert_never_closes(2)

    def test_single_successor(self):
        self._assert_never_closes(1)

    def test_publish_failure(self):
        receipt = self.receive(self._ordinary_piece())
        self.source.db.close()
        older = sign_report(self.offline, receipt)
        connection = self.offline.db
        attempts = []

        def deny_commit(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_INSERT and arg1 == 'signed_reports':
                attempts.append('insert')
            if action == sqlite3.SQLITE_TRANSACTION and arg1 == 'COMMIT':
                attempts.append('commit')
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_commit)
        try:
            with self.assertRaisesRegex(ReportSigningFailed, 'commit') as failure:
                sign_report(self.offline, receipt)
            self.assertIsInstance(failure.exception.__cause__, sqlite3.DatabaseError)
        finally:
            connection.set_authorizer(None)
        self.assertEqual(attempts, ['insert', 'commit'])
        self.assertFalse(connection.in_transaction)
        self.assertEqual(self.report_count(), 1)
        self.reopen_offline()
        self.assertEqual(self.report_count(), 1)
        self.assertEqual(get_report(self.offline, older.report_id), older)
        with self.assertRaises(ReportNotFound):
            get_report(self.offline, older.report_id + 1)
        self.assert_report(sign_report(self.offline, receipt), Fraction(1), Fraction(1))

    def test_completion_weight(self):
        evidence = self.issue(self._branching_root())
        receipt = self.receive(evidence)
        self.source.db.close()
        signed = sign_report(self.offline, receipt)
        expected = (Fraction(1, 3), ReviewExpectationKind.FINITE, Fraction(3, 2))
        result = signed.result
        actual = (result.completion_probability, result.review.kind, result.review.value)
        self.assertEqual(actual, expected, 'CONDITIONAL_REVIEW_MISMATCH')
        self.assertEqual(signed.provenance, evidence.provenance)
        archived = get_report(self.offline, signed.report_id)
        self.assertEqual(archived, signed)
        row = archived.result
        expected_export = {'probability': '1/3', 'review_kind': 'finite', 'review_count': '3/2'}
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v9',
            'input': {'ordinary_close_reviewed': 1, 'ordinary_two_children_unreviewed': 3, 'special_close_unreviewed': 1},
            'expected': expected_export,
            'actual': {'probability': str(actual[0]), 'review_kind': actual[1].value, 'review_count': str(actual[2])},
            'downstream_expected': expected_export | {'revision_matches': True},
            'downstream_actual': {
                'probability': str(row.completion_probability), 'review_kind': row.review.kind.value,
                'review_count': str(row.review.value), 'revision_matches': archived.provenance == evidence.provenance,
            },
            'code_paths': ['freeze/issue.py', 'freeze/receive.py', 'analysis/completion.py', 'analysis/review_work.py',
                           'handover/publish.py', 'handover/reports.py'],
            'oracle': 'q solves q = 1/4 + 3q^2/4 at its least root 1/3. The conditioned review rate is 3/4 and the conditioned mean number of children is 1/2.',
        }, ensure_ascii=False, sort_keys=True), flush=True)

    def test_same_marginals(self):
        root = self._branching_root()
        first = self.issue(root)
        first_receipt = self.receive(first)
        intermediate, _ = amend_revision(self.source, root.revision_id, 'C1', Disposition(0, 0, False))
        corrected, _ = amend_revision(self.source, intermediate.revision_id, 'C2', Disposition(2, 0, True))
        second = self.issue(corrected)
        second_receipt = self.receive(second)
        self.assertEqual(_marginals(first.rows), _marginals(second.rows))
        self.assertNotEqual(first.rows, second.rows)
        self.assertNotEqual(first_receipt, second_receipt)
        self.source.db.close()
        older = sign_report(self.offline, first_receipt)
        newer = sign_report(self.offline, second_receipt)
        self.assert_report(older, Fraction(1, 3), Fraction(3, 2))
        self.assert_report(newer, Fraction(1, 3), Fraction(1, 6))
        self.assertEqual(older.provenance, first.provenance)
        self.assertEqual(newer.provenance, second.provenance)
        self.reopen_offline()
        self.assertEqual(get_report(self.offline, older.report_id), older)
        self.assertEqual(get_report(self.offline, newer.report_id), newer)

    def test_critical_review(self):
        root = self.root(trial('C1', ordinary=2), trial('C2', special=1), special_trial('S1', review=True))
        corrected, _ = amend_revision(self.source, root.revision_id, 'S1', Disposition(0, 0, False))
        reviewed, unreviewed = (self.receive(self.issue(revision)) for revision in (root, corrected))
        self.source.db.close()
        infinite = sign_report(self.offline, reviewed)
        zero = sign_report(self.offline, unreviewed)
        self.assert_report(infinite, Fraction(1), None, ReviewExpectationKind.INFINITE)
        self.assert_report(zero, Fraction(1), Fraction(0))
        self.reopen_offline()
        self.assertEqual(get_report(self.offline, infinite.report_id), infinite)
        self.assertEqual(get_report(self.offline, zero.report_id), zero)
