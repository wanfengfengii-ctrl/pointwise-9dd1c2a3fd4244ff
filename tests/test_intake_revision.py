from intake.import_records import BatchRejected, record_batch
from intake.outcomes import Disposition, WorkClass
from intake.record_checks import InvalidDisposition
from intake.source_store import initialize_source
from ledger_sql import StoreInitializationError
from revision.amendments import RecordOutsideRevision, amend_revision
from revision.count_audit import audit_revision
from revision.revisions import RevisionNotFound
from revision.selection import select_revision_sample
from tests.support import LedgerCase, special_trial, trial


_ORDINARY = WorkClass.ORDINARY
_SPECIAL = WorkClass.SPECIAL


def _counts(audit):
    return {(row.work_class, row.disposition): row.count for row in audit.rows}


class TestIntake(LedgerCase):
    def _starting_batch(self):
        return self.root(trial('C1', review=True), trial('C2', ordinary=1), special_trial('S1'))

    def _source_sizes(self):
        db = self.source.db
        return (
            db.execute('SELECT count(*) FROM trial_batches').fetchone()[0],
            db.execute('SELECT count(*) FROM trial_records').fetchone()[0],
            db.execute('SELECT count(*) FROM revisions').fetchone()[0],
        )

    def test_count_revision(self):
        root = self._starting_batch()
        revision, changed = amend_revision(self.source, root.revision_id, 'C1', Disposition(0, 0, False))
        original = audit_revision(self.source, root.revision_id)
        common = {(_ORDINARY, Disposition(1, 0, False)): 1, (_SPECIAL, Disposition(0, 0, False)): 1}
        self.assertEqual(_counts(original), common | {(_ORDINARY, Disposition(0, 0, True)): 1})
        self.assertEqual(_counts(changed), common | {(_ORDINARY, Disposition(0, 0, False)): 1})
        for audit in (original, changed):
            self.assertEqual(audit.source_id, self.source.source_id)
            self.assertEqual(audit.batch_id, 'B01')
            self.assertEqual(audit.total_records, 3)
            self.assertEqual(dict(audit.class_totals), {_ORDINARY: 2, _SPECIAL: 1})
        self.assertEqual(revision.parent_id, root.revision_id)
        self.assertEqual(changed, audit_revision(self.source, revision.revision_id))
        original_rows = self.source.read_batch_records('B01')
        self.assertEqual(original_rows[0], trial('C1', review=True))
        changed_rows = select_revision_sample(self.source, revision.revision_id).records
        self.assertEqual(changed_rows[0], trial('C1'))

    def test_branch_from_parent(self):
        root = self._starting_batch()
        self.root(trial('OTHER'), batch='B02')
        first, _ = amend_revision(self.source, root.revision_id, 'C1', Disposition(0, 0, False))
        second, _ = amend_revision(self.source, root.revision_id, 'C2', Disposition(2, 0, True))
        self.assertEqual(first.parent_id, second.parent_id)
        special = {(_SPECIAL, Disposition(0, 0, False)): 1}
        for revision, dispositions in (
            (root, (Disposition(0, 0, True), Disposition(1, 0, False))),
            (first, (Disposition(0, 0, False), Disposition(1, 0, False))),
            (second, (Disposition(0, 0, True), Disposition(2, 0, True))),
        ):
            with self.subTest(revision=revision.revision_id):
                audit = audit_revision(self.source, revision.revision_id)
                self.assertEqual(_counts(audit), special | {(_ORDINARY, item): 1 for item in dispositions})
                self.assertEqual(dict(audit.class_totals), {_ORDINARY: 2, _SPECIAL: 1})
                self.assertEqual((audit.batch_id, audit.revision_id), ('B01', revision.revision_id))
        before = self._source_sizes()
        with self.assertRaises(RecordOutsideRevision):
            amend_revision(self.source, first.revision_id, 'OTHER', Disposition(0, 0, True))
        with self.assertRaises(InvalidDisposition):
            amend_revision(self.source, first.revision_id, 'S1', Disposition(0, 2, False))
        with self.assertRaises(RevisionNotFound):
            amend_revision(self.source, 9999, 'C1', Disposition(0, 0, True))
        self.assertEqual(self._source_sizes(), before)

    def test_invalid_special(self):
        root = self._starting_batch()
        original = audit_revision(self.source, root.revision_id)
        before = self._source_sizes()
        with self.assertRaises(InvalidDisposition):
            self.root(special_trial('BAD', successors=2), batch='BAD')
        self.assertEqual(self._source_sizes(), before)
        self.assertEqual(audit_revision(self.source, root.revision_id), original)

    def test_mixed_batch(self):
        root = self._starting_batch()
        before = self._source_sizes()
        original = self.source.read_batch_records(root.batch_id)
        with self.assertRaises(InvalidDisposition):
            self.root(trial('NEW'), special_trial('BAD', successors=2), batch='BAD')
        with self.assertRaises(BatchRejected):
            self.root(trial('NEW'), trial('C1'), batch='CONFLICT')
        with self.assertRaises(BatchRejected):
            self.root(trial('NEW'), trial('NEW'), batch='DUPLICATE')
        self.assertEqual(self._source_sizes(), before)
        self.assertEqual(self.source.read_batch_records(root.batch_id), original)
        self.assertEqual(self.source.read_batch_records('CONFLICT'), ())
        admitted = record_batch(self.source, 'RECOVERED', [trial('NEW')])
        self.assertEqual(audit_revision(self.source, admitted.revision_id).total_records, 1)

    def test_reinitialize(self):
        root = self._starting_batch()
        original = audit_revision(self.source, root.revision_id)
        revision, changed = amend_revision(self.source, root.revision_id, 'C1', Disposition(0, 0, False))
        raw = self.source.read_batch_records(root.batch_id)
        self.source.db.close()
        connection = self.connect(self.source_path)
        self.source = initialize_source(connection)
        self.source = initialize_source(connection)
        self.assertEqual(self.source.source_id, original.source_id)
        self.assertEqual(self.source.read_batch_records(root.batch_id), raw)
        self.assertEqual(audit_revision(self.source, root.revision_id), original)
        self.assertEqual(audit_revision(self.source, revision.revision_id), changed)

    def test_store_kind(self):
        other = self.connect(self.directory / 'other.sqlite')
        other.execute('CREATE TABLE custodian (value TEXT NOT NULL)')
        other.execute('INSERT INTO custodian VALUES (?)', ('keep',))
        other.commit()
        with self.assertRaises(StoreInitializationError):
            initialize_source(other)
        self.assertEqual(other.execute('SELECT value FROM custodian').fetchall(), [('keep',)])
        self.assertEqual(other.execute('PRAGMA application_id').fetchone()[0], 0)

    def test_incompatible_structure(self):
        root = self._starting_batch()
        connection = self.source.db
        connection.execute('DROP INDEX revision_root')
        with self.assertRaises(StoreInitializationError):
            initialize_source(connection)
        self.assertEqual(audit_revision(self.source, root.revision_id).total_records, 3)
        indexes = connection.execute('PRAGMA index_list(revisions)').fetchall()
        self.assertNotIn('revision_root', [index[1] for index in indexes])
