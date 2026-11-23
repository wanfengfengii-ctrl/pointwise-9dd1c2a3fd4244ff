from fractions import Fraction
import json
import sqlite3

from analysis.mixture import build_mixture_model, mixture_interval_passes
from analysis.report_result import compute_report_result
from analysis.review_work import ReviewExpectationKind
from freeze.evidence import FrozenEvidence
from freeze.evidence_codec import encode_evidence
from freeze.evidence_store import EVIDENCE_SCHEMA
from freeze.frequency import JointFrequency
from freeze.issue import IssuanceRejected, freeze_mix
from freeze.receive import ReceiptRejected, load_received_evidence, receive_evidence, receive_mix
from handover.publish import ReportSigningFailed, sign_mix_report, sign_report
from handover.report_store import REPORT_SCHEMA, ReportStore, initialize_offline
from handover.reports import ReportNotFound, get_mix_report, get_report
from ledger_sql import write_transaction
from mix_fixture import issue_pair
from tests.support import LedgerCase, special_trial, trial


class MixtureCase(LedgerCase):
    def setUp(self):
        super().setUp()
        self._pairs = {}

    def pair(self, name='critical', right_copies=1):
        key = (name, right_copies)
        if key not in self._pairs:
            self._pairs[key] = issue_pair(self.source, name, right_copies=right_copies)
        return self._pairs[key]

    def mixture(self, name='critical', right_copies=1, low=0, high=1):
        left, right = self.pair(name, right_copies)
        left_payload, right_payload = encode_evidence(left), encode_evidence(right)
        mix_id, manifest = freeze_mix(left_payload, right_payload, low, high)
        return left, right, left_payload, right_payload, mix_id, manifest

    def receive(self, mix_id, manifest, left_payload, right_payload):
        return receive_mix(self.offline, mix_id, manifest, left_payload, right_payload)

    def sign(self, receipt, completion_min, review_max):
        # The night shift signs after the source ledger is shut down.
        self.source.db.close()
        return sign_mix_report(self.offline, receipt, completion_min, review_max)

    def mixture_count(self):
        return self.offline.db.execute('SELECT count(*) FROM received_mixtures').fetchone()[0]

    def mix_report_count(self):
        return self.offline.db.execute('SELECT count(*) FROM mix_reports').fetchone()[0]


class TestFreezeMix(MixtureCase):
    def test_deterministic(self):
        _, _, left_payload, right_payload, _, _ = self.mixture()
        first = freeze_mix(left_payload, right_payload, 0, 1)
        second = freeze_mix(left_payload, right_payload, Fraction(0), Fraction(1))
        self.assertEqual(first, second)
        self.assertIsInstance(first[0], str)
        self.assertIsInstance(first[1], bytes)
        third = freeze_mix(left_payload, right_payload, Fraction(1, 2), Fraction(2, 4))
        self.assertEqual(third, freeze_mix(left_payload, right_payload, Fraction(1, 2), Fraction(1, 2)))
        self.assertNotEqual(first[0], third[0])
        swapped = freeze_mix(right_payload, left_payload, 0, 1)
        self.assertNotEqual(first[0], swapped[0])
        self.assertNotEqual(first[1], swapped[1])

    def test_invalid_bounds(self):
        _, _, left_payload, right_payload, _, _ = self.mixture()
        for low, high in (
            (True, 1), (0, True), ('0', 1), (0, '1'), (0.0, 1), (0, 1.0), (None, 1),
            (-1, 1), (0, 2), (Fraction(1, 2), Fraction(1, 3)), (Fraction(-1, 2), 1),
        ):
            with self.subTest(low=low, high=high), self.assertRaises(IssuanceRejected):
                freeze_mix(left_payload, right_payload, low, high)

    def test_invalid_payloads(self):
        _, _, left_payload, right_payload, _, _ = self.mixture()
        for left, right in (
            (b'', right_payload), (left_payload, b'{}'), (b'not json', right_payload),
            (None, right_payload), (left_payload, right_payload + b' '),
        ):
            with self.subTest(), self.assertRaises(IssuanceRejected):
                freeze_mix(left, right, 0, 1)


class TestReceiveMix(MixtureCase):
    def test_receive_and_redeliver(self):
        left, right, left_payload, right_payload, mix_id, manifest = self.mixture(low=0, high=1)
        receipt = self.receive(mix_id, manifest, left_payload, right_payload)
        self.assertEqual(receipt, mix_id)
        self.assertEqual(self.receive(mix_id, manifest, left_payload, right_payload), mix_id)
        self.assertEqual((self.mixture_count(), self.evidence_count()), (1, 2))
        # The receipt id retrieves both frozen parents and the exact window.
        stored = self.offline.find_mixture(receipt)
        self.assertEqual((stored.low, stored.high), (Fraction(0), Fraction(1)))
        self.assertEqual(load_received_evidence(self.offline.evidence, stored.left_id).rows, left.rows)
        self.assertEqual(load_received_evidence(self.offline.evidence, stored.right_id).rows, right.rows)

    def test_rejections(self):
        _, _, left_payload, right_payload, mix_id, manifest = self.mixture(low=0, high=1)
        _, _, _, _, zero_id, zero_manifest = self.mixture(low=0, high=0)
        envelope = json.loads(manifest)
        widened = dict(envelope, body=dict(envelope['body'], high='1/2'))
        tampered = json.dumps(widened, sort_keys=True, separators=(',', ':')).encode('ascii')
        spaced = json.dumps(json.loads(manifest), sort_keys=True).encode('ascii')
        attempts = [
            ('wrong-expected', manifest, left_payload, right_payload),
            (zero_id, manifest, left_payload, right_payload),      # window delivered under another id
            (mix_id, zero_manifest, left_payload, right_payload),  # other window under this id
            (mix_id, tampered, left_payload, right_payload),       # modified window
            (mix_id, spaced, left_payload, right_payload),         # non-canonical body
            (mix_id, b'', left_payload, right_payload),
            (mix_id, manifest, right_payload, left_payload),       # reversed parents
            (mix_id, manifest, left_payload, left_payload),        # wrong right item
            (mix_id, manifest, b'', right_payload),
            (mix_id, manifest, left_payload, b'corrupted'),
        ]
        for expected, body, left, right in attempts:
            with self.subTest(expected=expected):
                with self.assertRaises(ReceiptRejected):
                    receive_mix(self.offline, expected, body, left, right)
        self.assertEqual((self.mixture_count(), self.evidence_count()), (0, 0))

    def test_same_frequencies_different_identity(self):
        # Identical dispositions share joint frequencies but not the V1
        # identity; the manifest binds the exact ordered parents.
        first = self.issue(self.root(trial('C1', review=True), trial('C2', ordinary=2), special_trial('S1')))
        second = self.issue(self.root(trial('D1', review=True), trial('D2', ordinary=2), special_trial('S2'), batch='B02'))
        self.assertEqual(first.rows, second.rows)
        self.assertNotEqual(first.provenance.evidence_id, second.provenance.evidence_id)
        mix_id, manifest = freeze_mix(encode_evidence(first), encode_evidence(first), 0, 1)
        with self.assertRaises(ReceiptRejected):
            receive_mix(self.offline, mix_id, manifest, encode_evidence(first), encode_evidence(second))
        with self.assertRaises(ReceiptRejected):
            receive_mix(self.offline, mix_id, manifest, encode_evidence(second), encode_evidence(first))
        receipt = receive_mix(self.offline, mix_id, manifest, encode_evidence(first), encode_evidence(first))
        self.assertEqual(receipt, mix_id)


class TestSignMixReport(MixtureCase):
    def test_threshold_validation(self):
        _, _, left_payload, right_payload, mix_id, manifest = self.mixture()
        self.receive(mix_id, manifest, left_payload, right_payload)
        for completion_min in (True, 0, -1, Fraction(0), Fraction(-1, 2), '1', 0.5, None):
            with self.subTest(completion_min=completion_min), self.assertRaises(ValueError):
                self.sign(mix_id, completion_min, 1)
        for review_max in (True, -1, Fraction(-1, 3), '2', 0.5, None):
            with self.subTest(review_max=review_max), self.assertRaises(ValueError):
                self.sign(mix_id, 1, review_max)
        self.assertEqual(self.mix_report_count(), 0)

    def test_missing_receipt(self):
        _, _, _, _, mix_id, _ = self.mixture()
        with self.assertRaises(ReportSigningFailed):
            self.sign(mix_id, 1, 1)
        with self.assertRaises(ReportSigningFailed):
            self.sign('not-a-receipt', 1, 1)
        with self.assertRaises(ReportSigningFailed):
            self.sign(12, 1, 1)
        self.assertEqual(self.mix_report_count(), 0)

    def test_commit_failure_rolls_back(self):
        _, _, left_payload, right_payload, mix_id, manifest = self.mixture()
        receipt = self.receive(mix_id, manifest, left_payload, right_payload)
        report_id, passed = self.sign(receipt, Fraction(1, 3), 2)
        self.assertIs(passed, False)
        connection = self.offline.db
        attempts = []

        def deny_commit(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_INSERT and arg1 == 'mix_reports':
                attempts.append('insert')
            if action == sqlite3.SQLITE_TRANSACTION and arg1 == 'COMMIT':
                attempts.append('commit')
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_commit)
        try:
            with self.assertRaisesRegex(ReportSigningFailed, 'commit') as failure:
                self.sign(receipt, 1, 4)
            self.assertIsInstance(failure.exception.__cause__, sqlite3.DatabaseError)
        finally:
            connection.set_authorizer(None)
        self.assertEqual(attempts, ['insert', 'commit'])
        self.assertFalse(connection.in_transaction)
        self.assertEqual(self.mix_report_count(), 1)
        self.reopen_offline()
        self.assertEqual(self.mix_report_count(), 1)
        self.assertEqual(get_mix_report(self.offline, report_id)[0], False)
        retry_id, retry_passed = self.sign(receipt, 1, 4)
        self.assertIs(retry_passed, False)
        self.assertNotEqual(retry_id, report_id)
        self.assertEqual(self.mix_report_count(), 2)

    def test_report_shape_and_unknown(self):
        left, right, left_payload, right_payload, mix_id, manifest = self.mixture()
        receipt = self.receive(mix_id, manifest, left_payload, right_payload)
        report_id, passed = self.sign(receipt, Fraction(1, 3), Fraction(2))
        self.assertIs(type(report_id), int)
        self.assertGreater(report_id, 0)
        self.assertIs(type(passed), bool)
        record = get_mix_report(self.offline, report_id)
        self.assertEqual(record[0], passed)
        self.assertEqual(record[1], mix_id)
        self.assertEqual(record[2], (left.provenance, right.provenance))
        self.assertEqual(record[3], (Fraction(0), Fraction(1)))
        self.assertEqual(record[4], (Fraction(1, 3), Fraction(2)))
        self.assertIsInstance(record[2][0], type(left.provenance))
        with self.assertRaises(ReportNotFound):
            get_mix_report(self.offline, report_id + 1)
        with self.assertRaises(ReportNotFound):
            get_mix_report(self.offline, 'x')


class TestMixtureCalibrations(MixtureCase):
    def assert_window(self, name, low, high, completion_min, review_max, expected, right_copies=1):
        _, _, left_payload, right_payload, mix_id, manifest = self.mixture(
            name, right_copies=right_copies, low=low, high=high,
        )
        receipt = self.receive(mix_id, manifest, left_payload, right_payload)
        report_id, passed = self.sign(receipt, completion_min, review_max)
        self.assertIs(passed, expected, f'{name} [{low}, {high}]')
        self.assertEqual(get_mix_report(self.offline, report_id)[0], expected)

    def _assert_critical_windows(self, copies):
        third = Fraction(1, 3)
        self.assert_window('critical', 0, 0, third, 2, True, copies)
        self.assert_window('critical', 1, 1, third, 2, True, copies)
        self.assert_window('critical', 0, 1, third, 2, False, copies)
        self.assert_window('critical', Fraction(1, 2), Fraction(1, 2), third, 4, False, copies)

    def test_critical(self):
        self._assert_critical_windows(1)

    def test_critical_duplicated_right(self):
        # Duplicating the right sample keeps every judgment unchanged.
        self._assert_critical_windows(2)

    def test_zero_knot(self):
        self.assert_window('zero-knot', 0, 0, 1, 2, True)
        self.assert_window('zero-knot', 0, 1, 1, 2, False)
        self.assert_window('zero-knot', 0, 1, 1, 4, True)

    def test_interior_peak(self):
        self.assert_window('interior-peak', 0, 1, 1, Fraction(17, 50), False)
        self.assert_window('interior-peak', 0, 1, 1, Fraction(7, 20), True)
        self.assert_window('interior-peak', Fraction(1, 2), Fraction(1, 2), 1, Fraction(1, 3), True)
        self.assert_window('interior-peak', Fraction(3, 5), Fraction(3, 5), 1, Fraction(12, 35), True)
        self.assert_window('interior-peak', Fraction(3, 5), Fraction(3, 5), 1, Fraction(17, 50), False)

    def test_renewal(self):
        self.assert_window('renewal', 0, 1, 1, 0, False)
        self.assert_window('renewal', Fraction(1, 10), 1, 1, 0, True)

    def test_inclusive_thresholds(self):
        # Endpoints of the sample cases meet their limits with equality.
        self.pair('critical')
        self.pair('zero-knot')
        self.pair('interior-peak')
        self.assert_window('critical', 1, 1, Fraction(1, 3), Fraction(3, 2), True)
        self.assert_window('critical', 0, 0, 1, Fraction(3, 2), True)
        self.assert_window('zero-knot', 1, 1, 1, 4, True)
        self.assert_window('interior-peak', Fraction(3, 5), Fraction(3, 5), 1, Fraction(12, 35), True)
        # The interior peak sits at the irrational ratio 2 - sqrt(2) with value
        # 6 - 4*sqrt(2), strictly above 12/35, so the full window fails there.
        self.assert_window('interior-peak', 0, 1, 1, Fraction(12, 35), False)
        self.assert_window('interior-peak', 0, 1, 1, Fraction(1, 3), False)


class TestMixtureConsistency(MixtureCase):
    def _point_verdict(self, left_rows, right_rows, t, completion_min, review_max):
        merged = {}
        for rows, weight in ((left_rows, 1 - t), (right_rows, t)):
            for row in rows:
                key = (row.work_class, row.disposition)
                merged[key] = merged.get(key, Fraction(0)) + weight * row.frequency
        rows = tuple(
            JointFrequency(kind, disposition, 1, frequency)
            for (kind, disposition), frequency in sorted(merged.items())
            if frequency > 0
        )
        result = compute_report_result(FrozenEvidence(None, rows))
        if result.completion_probability < completion_min:
            return False
        review = result.review
        if review.kind is not ReviewExpectationKind.FINITE:
            return False
        return review.value <= review_max

    def test_interval_matches_dense_points(self):
        thresholds = (
            (Fraction(1, 3), Fraction(2)), (Fraction(1), Fraction(7, 20)),
            (Fraction(1), Fraction(4)), (Fraction(1), Fraction(0)),
        )
        for name in ('critical', 'zero-knot', 'interior-peak', 'renewal'):
            left, right = self.pair(name)
            model = build_mixture_model(left.rows, right.rows)
            for completion_min, review_max in thresholds:
                for num in range(0, 11):
                    low = Fraction(num, 10)
                    for high_num in range(num, 11, 3):
                        high = Fraction(high_num, 10)
                        exact = mixture_interval_passes(model, low, high, completion_min, review_max)
                        samples = [
                            self._point_verdict(
                                left.rows, right.rows,
                                low + Fraction(step, 50) * (high - low),
                                completion_min, review_max,
                            )
                            for step in range(51)
                        ]
                        self.assertEqual(exact, all(samples), (name, low, high, completion_min, review_max))

    def test_degenerate_window_matches_point(self):
        for name in ('critical', 'zero-knot', 'interior-peak', 'renewal'):
            left, right = self.pair(name)
            model = build_mixture_model(left.rows, right.rows)
            for num in range(0, 11):
                point = Fraction(num, 10)
                for completion_min, review_max in ((Fraction(1, 3), Fraction(2)), (Fraction(1), Fraction(3))):
                    exact = mixture_interval_passes(model, point, point, completion_min, review_max)
                    sample = self._point_verdict(left.rows, right.rows, point, completion_min, review_max)
                    self.assertEqual(exact, sample, (name, point, completion_min, review_max))


class TestMixturePersistence(MixtureCase):
    def test_reopen_reads_archived_verdicts(self):
        left, right, left_payload, right_payload, mix_id, manifest = self.mixture()
        receipt = self.receive(mix_id, manifest, left_payload, right_payload)
        v1_left = receive_evidence(self.offline.evidence, left_payload, left.provenance)
        v1_report = sign_report(self.offline, v1_left)
        report_id, passed = self.sign(receipt, Fraction(1, 3), 2)
        self.assertIs(passed, False)
        self.reopen_offline()
        record = get_mix_report(self.offline, report_id)
        self.assertEqual(record[0], False)
        self.assertEqual(record[1], mix_id)
        self.assertEqual(record[2], (left.provenance, right.provenance))
        self.assertEqual(record[3], (Fraction(0), Fraction(1)))
        self.assertEqual(record[4], (Fraction(1, 3), Fraction(2)))
        # Old V1 reports keep their original entry point and number.
        self.assertEqual(get_report(self.offline, v1_report.report_id), v1_report)

    def test_legacy_v1_ledger_upgrades(self):
        # A ledger written by the V1-only version gains the mixture tables
        # without losing the stored receipts and reports.
        legacy = self.connect(self.directory / 'legacy.sqlite')
        with write_transaction(legacy):
            for statement in (EVIDENCE_SCHEMA | REPORT_SCHEMA).values():
                legacy.execute(statement)
            legacy.execute(f'PRAGMA application_id = {0x52504F31}')
            legacy.execute('PRAGMA user_version = 1')
        store = ReportStore(legacy)
        evidence = self.issue(self.root(trial('C1', review=True), special_trial('S1')))
        receipt = receive_evidence(store.evidence, encode_evidence(evidence), evidence.provenance)
        signed = sign_report(store, receipt)
        legacy.close()
        upgraded = initialize_offline(self.connect(self.directory / 'legacy.sqlite'))
        self.assertEqual(get_report(upgraded, signed.report_id), signed)
        names = {row[0] for row in upgraded.db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
        self.assertTrue({'received_mixtures', 'mix_reports'} <= names)
        # The upgraded ledger takes part in the mixture flow.
        _, _, left_payload, right_payload, mix_id, manifest = self.mixture()
        receipt = receive_mix(upgraded, mix_id, manifest, left_payload, right_payload)
        self.source.db.close()
        report_id, passed = sign_mix_report(upgraded, receipt, 1, 4)
        self.assertIs(passed, False)
        self.assertEqual(get_mix_report(upgraded, report_id)[1], mix_id)
